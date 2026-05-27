"""mevzuat-mcp client — Türk mevzuatına MCP JSON-RPC üzerinden erişim.

Said Sürücü'nün mevzuat-mcp projesi (yargi-mcp ile aynı ekosistem).
Public endpoint: https://mevzuat.surucu.dev/mcp

İki yol var:
1. **Bedesten unified** (önerilen): `search_mevzuat(mevzuat_no=6502)` →
   `get_mevzuat_content(mevzuat_id)` → full Markdown
2. mevzuat.gov.tr legacy: `search_kanun()` + `search_within_kanun()`

Kullanım:
    async with MevzuatClient() as client:
        mevzuat_id = await client.find_kanun_id(numara="6502")
        markdown = await client.get_content(mevzuat_id)

Repo: https://github.com/saidsurucu/mevzuat-mcp
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from retrieval.mcp_base import PROTOCOL_VERSION, SESSION_HEADER, parse_mcp_response

logger = logging.getLogger(__name__)

MEVZUAT_MCP_URL = os.getenv("MEVZUAT_MCP_URL", "https://mevzuat.surucu.dev/mcp")
MEVZUAT_MCP_TIMEOUT_MS = int(os.getenv("MEVZUAT_MCP_TIMEOUT_MS", "30000"))

# Türk hukukunun temel kanun numaraları → kanun kodları
# Kapsam (CLAUDE.md §4): tuketici, isHukuku, kira, icra, trafik, vergi, tapu, idari
# Ceza/aile YOK; TCK sadece referans için (graph CITES edge'leri için, doğrudan
# kullanılmaz). Bu liste seed_mevzuat ve scripts/build_graph tarafından okunur.
# Sprint-5 W12: 17 → 41 kanun. Her domain için 5+ ilgili kanun.
KANUN_KODU_TO_NUMARA: dict[str, str] = {
    # --- Çekirdek hukuk ---
    "TBK": "6098",      # Türk Borçlar Kanunu (kira: m.299-378; satım: m.207-281)
    "IK": "4857",       # İş Kanunu
    "TKHK": "6502",     # Tüketicinin Korunması Hakkında Kanun
    "TMK": "4721",      # Türk Medeni Kanunu
    "ANAYASA": "2709",  # T.C. Anayasası
    # --- Usul kanunları ---
    "HMK": "6100",      # Hukuk Muhakemeleri Kanunu (dava usulü, dilekçe formatı)
    "IYUK": "2577",     # İdari Yargılama Usulü Kanunu (idari dava, iptal)
    "IIK": "2004",      # İcra ve İflas Kanunu (haciz, takip — icra domain)
    # --- Sosyal güvenlik + iş hukuku tamamlayıcılar ---
    "SGK": "5510",      # Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu
    "SK": "6356",       # Sendikalar ve Toplu İş Sözleşmesi Kanunu
    "ISGK": "6331",     # İş Sağlığı ve Güvenliği Kanunu
    "DMK": "657",       # Devlet Memurları Kanunu (kamu personeli)
    "DIK": "854",       # Deniz İş Kanunu (gemi çalışanları)
    "BMC": "5953",      # Basın Mesleğinde Çalışanlar Kanunu
    "OGK": "5188",      # Özel Güvenlik Hizmetleri Kanunu
    # --- Ticaret + tüketici ekonomik düzen ---
    "TTK": "6102",      # Türk Ticaret Kanunu (e-ticaret, ticari satım, kambiyo)
    "BK": "5411",       # Bankacılık Kanunu (kredi, mevduat)
    "SIGORTA": "5684",  # Sigortacılık Kanunu (trafik, tüketici sigorta)
    "RKHK": "4054",     # Rekabetin Korunması Hakkında Kanun
    "KVKK": "6698",     # Kişisel Verilerin Korunması Kanunu
    "OHK": "6493",      # Ödeme ve Menkul Kıymet Mutabakat Hizmetleri Kanunu
    # --- Vergi + mali ---
    "VUK": "213",       # Vergi Usul Kanunu
    "GVK": "193",       # Gelir Vergisi Kanunu
    "KVK": "5520",      # Kurumlar Vergisi Kanunu
    "KDV": "3065",      # Katma Değer Vergisi Kanunu
    "OTV": "4760",      # Özel Tüketim Vergisi Kanunu
    "DV": "488",        # Damga Vergisi Kanunu
    "MTV": "197",       # Motorlu Taşıtlar Vergisi Kanunu
    "EMLAKV": "1319",   # Emlak Vergisi Kanunu
    "AATUHK": "6183",   # Amme Alacaklarının Tahsil Usulü Kanunu
    "MYK": "5018",      # Kamu Mali Yönetimi ve Kontrol Kanunu
    # --- Trafik + ulaşım ---
    "KTK": "2918",      # Karayolları Trafik Kanunu (TK alias)
    "TK": "2918",       # KTK eski isim (geri uyumluluk)
    "KGK": "4925",      # Karayolu Taşıma Kanunu
    # --- Tapu + imar ---
    "TPK": "2644",      # Tapu Kanunu (KK alias)
    "KK": "2644",       # Tapu Kanunu eski isim
    "KMK": "634",       # Kat Mülkiyeti Kanunu
    "IMARK": "3194",    # İmar Kanunu
    "KAMK": "2942",     # Kamulaştırma Kanunu
    "KDK": "6306",      # Afet Riski Altındaki Alanların Dönüştürülmesi (Kentsel Dönüşüm)
    # --- İdari + kamu yönetimi ---
    "IHK": "4734",      # Kamu İhale Kanunu
    "IHSK": "4735",     # Kamu İhale Sözleşmeleri Kanunu
    "DIHK": "3071",     # Dilekçe Hakkı Kanunu
    "BLDK": "5393",     # Belediye Kanunu
    "IOIK": "5302",     # İl Özel İdaresi Kanunu
    "CK": "2872",       # Çevre Kanunu
    "GIBK": "5345",     # Gelir İdaresi Başkanlığı Teşkilat Kanunu
    # --- Afet + sosyal yardım ---
    "AYK": "7269",      # Umumi Hayata Müessir Afetler Kanunu
    # --- Referans (kapsam dışı ama graph cite için) ---
    "TCK": "5237",      # Türk Ceza Kanunu — DİREKT KULLANILMAZ
}


@dataclass(slots=True)
class MevzuatRef:
    """search_mevzuat sonucundan tek bir mevzuat kaydı."""

    mevzuat_id: str
    mevzuat_no: str | None
    mevzuat_adi: str
    mevzuat_tur: str | None
    resmi_gazete_tarihi: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Madde:
    """Tek bir kanun maddesi — chunk + citation verification için."""

    kanun_kodu: str
    kanun_numarasi: str
    kanun_adi: str
    madde_no: int
    baslik: str | None
    metin: str
    source_url: str

    @property
    def id(self) -> str:
        return f"m-{self.kanun_kodu}-{self.madde_no}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "doc_id": self.id,
            "doc_type": "law",
            "kanun_kodu": self.kanun_kodu,
            "kanun_numarasi": self.kanun_numarasi,
            "kanun_adi": self.kanun_adi,
            "madde_no": self.madde_no,
            "baslik": self.baslik,
            "source": "mevzuat",
            "source_url": self.source_url,
        }


class MevzuatClient:
    """mevzuat-mcp MCP JSON-RPC client. `async with` ile kullanın."""

    def __init__(
        self,
        base_url: str = MEVZUAT_MCP_URL,
        timeout_ms: int = MEVZUAT_MCP_TIMEOUT_MS,
    ) -> None:
        self.base_url = base_url
        self._timeout = timeout_ms / 1000.0
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._rpc_id = 0
        self._initialized = False

    async def __aenter__(self) -> MevzuatClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            follow_redirects=True,
        )
        await self._initialize()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            self._initialized = False

    async def _initialize(self) -> None:
        if self._initialized:
            return
        # assert yerine açık guard — `python -O` ile assert strip edilir (sessiz bug).
        if self._client is None:
            raise RuntimeError("MevzuatClient 'async with' bloğunda kullanılmalı")
        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adalet-agent", "version": "0.1"},
            },
        }
        resp = await self._client.post("", json=payload)
        self._session_id = resp.headers.get(SESSION_HEADER)
        if not self._session_id:
            raise RuntimeError(f"mevzuat-mcp session ID alınamadı: {resp.status_code}")
        # notifications/initialized
        await self._client.post(
            "",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={SESSION_HEADER: self._session_id},
        )
        self._initialized = True
        logger.info("mevzuat_mcp_initialized", extra={"session_id": self._session_id[:8]})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._client is None or self._session_id is None:
            raise RuntimeError("MevzuatClient: session başlatılmadı (_initialize)")
        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        resp = await self._client.post(
            "",
            json=payload,
            headers={SESSION_HEADER: self._session_id},
        )
        resp.raise_for_status()
        data = parse_mcp_response(resp.text)
        if "error" in data:
            raise RuntimeError(f"mevzuat-mcp error: {data['error']}")
        result = data.get("result", {})
        # MCP tool çıktısı: {"content": [{"type": "text", "text": "<JSON string>"}]}
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "{}")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw_text": text}
        return result

    async def search_kanun_by_no(self, mevzuat_no: str) -> list[MevzuatRef]:
        """Bir kanun numarasından kanun listesi (genelde tek sonuç döner)."""
        data = await self._call_tool(
            "search_mevzuat",
            {"mevzuat_no": mevzuat_no, "mevzuat_tur": "KANUN"},
        )
        items = (
            data.get("results")
            or data.get("documents")
            or data.get("mevzuat_list")
            or []
        )
        return [_parse_mevzuat_ref(item) for item in items if item.get("mevzuat_id") or item.get("id")]

    async def get_content(self, mevzuat_id: str) -> str:
        """Tam kanun metnini Markdown formatında al."""
        data = await self._call_tool(
            "get_mevzuat_content",
            {"mevzuat_id": mevzuat_id},
        )
        # Olası field isimleri:
        return (
            data.get("markdown_content")
            or data.get("markdown")
            or data.get("content")
            or data.get("text")
            or ""
        )

    async def get_madde_tree(self, mevzuat_id: str) -> list[dict[str, Any]]:
        """Madde içindekiler ağacı — büyük kanunlarda navigasyon için."""
        data = await self._call_tool(
            "get_mevzuat_madde_tree",
            {"mevzuat_id": mevzuat_id},
        )
        return data.get("nodes") or data.get("tree") or data.get("items") or []


def _parse_mevzuat_ref(item: dict[str, Any]) -> MevzuatRef:
    return MevzuatRef(
        mevzuat_id=str(item.get("mevzuat_id") or item.get("id") or ""),
        mevzuat_no=item.get("mevzuat_no") or item.get("kanun_numarasi"),
        mevzuat_adi=item.get("mevzuat_adi") or item.get("title") or item.get("ad") or "",
        mevzuat_tur=item.get("mevzuat_tur") or item.get("type"),
        resmi_gazete_tarihi=item.get("resmi_gazete_tarihi"),
        raw=item,
    )
