"""Direct mevzuat.gov.tr yönetmelik seed — auth-siz HTML iframe endpoint.

mevzuat-mcp'yi bypass edip doğrulanmış MevzuatNo'larla doğrudan çekiyoruz.
Endpoint: anasayfa/MevzuatFihristDetayIframe?MevzuatTur=7&MevzuatNo=X&MevzuatTertip=5
Public, auth yok, CAPTCHA yok.

Kullanım: uv run python -m scripts.seed_yonetmelik_direct
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

import httpx
from bs4 import BeautifulSoup

from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_decision
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks

logger = logging.getLogger("scripts.seed_yonetmelik_direct")

# (mevzuat_no, mevzuat_tur_str, mevzuat_tertip, kanun_kodu, kanun_adi, domain)
# kanun_kodu domain-scoped retrieval için DOMAIN_TO_KANUN_KODU'ya eklenebilir
# (config.py manuel edit). Şimdilik sadece chunk payload'a yazılır.
TARGETS: tuple[tuple[str, str, str, str, str, str], ...] = (
    # Tüketici yönetmelikleri (agent araştırması ile doğrulandı)
    ("20237", "7", "5", "YON_MESAFELI", "Mesafeli Sözleşmeler Yönetmeliği", "tuketici"),
    ("19782", "7", "5", "YON_GARANTI", "Garanti Belgesi Yönetmeliği", "tuketici"),
    ("19783", "7", "5", "YON_SSH", "Satış Sonrası Hizmetler Yönetmeliği", "tuketici"),
    ("39730", "7", "5", "YON_HAKEM", "Tüketici Hakem Heyetleri Yönetmeliği (2022)", "tuketici"),
    ("20239", "7", "5", "YON_HAKEM_ESKI", "Tüketici Hakem Heyetleri Yönetmeliği (2014)", "tuketici"),
)

# Doğrulanmış public endpoint (auth yok)
IFRAME_URL = (
    "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe"
    "?MevzuatTur={tur}&MevzuatNo={no}&MevzuatTertip={tertip}"
)
PUBLIC_URL = (
    "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={no}&MevzuatTur={tur}&MevzuatTertip={tertip}"
)

# Madde parser — "Madde N" + içerik
_MADDE_RE = re.compile(r"(?:^|\n)\s*(Madde\s+\d+[A-ZÇĞİÖŞÜa-zçğıöşü\s\-/]{0,40})\s*[-—–:]?", re.M)


async def _fetch_html(client: httpx.AsyncClient, mev_no: str, tur: str, tertip: str) -> str:
    """Iframe HTML'i çek, sadece text döndür."""
    url = IFRAME_URL.format(no=mev_no, tur=tur, tertip=tertip)
    resp = await client.get(url, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # Script + style at
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Çoklu boşluk + boş satırları normalize et
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


async def _seed_one(
    client: httpx.AsyncClient,
    embedder: Embedder,
    qdrant,
    mev_no: str, tur: str, tertip: str,
    kanun_kodu: str, kanun_adi: str, domain: str,
) -> int:
    """Tek bir yönetmeliği çek + chunk + embed + upsert."""
    logger.info("yonetmelik_started no=%s kod=%s ad=%s", mev_no, kanun_kodu, kanun_adi)
    try:
        text = await _fetch_html(client, mev_no, tur, tertip)
    except Exception as exc:
        logger.warning("fetch_failed no=%s err=%s", mev_no, str(exc)[:120])
        return 0
    if not text or len(text) < 500:
        logger.warning("short_text no=%s len=%d", mev_no, len(text))
        return 0
    logger.info("yonetmelik_fetched no=%s text_len=%d", mev_no, len(text))

    # chunk_decision genel markdown parser; yönetmelik için yeterli
    chunks = chunk_decision(text)
    if not chunks:
        logger.warning("no_chunks no=%s", mev_no)
        return 0

    source_url = PUBLIC_URL.format(no=mev_no, tur=tur, tertip=tertip)
    base = {
        "doc_id": f"y-{kanun_kodu}",
        "court": None,
        "chamber": kanun_adi,
        "date": None,
        "title": kanun_adi,
        "source": "mevzuat",
        "source_url": source_url,
        "domain": domain,
        "doc_type": "regulation",  # kanun değil, yönetmelik
        "kanun_kodu": kanun_kodu,
        "mevzuat_no": mev_no,
        "mevzuat_tur": tur,
    }

    # Maddeleri bulup metadata olarak işaretle (basit yaklaşım: madde başlığını chunk
    # başlangıcından regex ile ayıkla)
    points = []
    for seq, c in enumerate(chunks):
        madde_match = _MADDE_RE.search(c.text[:200])
        madde_no = madde_match.group(1).strip() if madde_match else f"chunk-{seq}"
        cid = f"y-{kanun_kodu}-c{seq}"
        payload = {
            **base, "chunk_id": cid, "chunk_seq": seq,
            "text": c.text, "madde_no": madde_no,
            "section": c.metadata.get("section", "icerik"),
        }
        points.append((c.text, cid, payload))

    # Embed + upsert
    texts = [t for t, _, _ in points]
    out = await asyncio.to_thread(embedder.encode, texts, 8)
    qd_points = [
        ChunkPoint(
            id=cid, dense_vector=dense,
            sparse_indices=sparse[0], sparse_values=sparse[1],
            payload=payload,
        )
        for (_, cid, payload), dense, sparse in zip(points, out.dense, out.sparse)
    ]
    await upsert_chunks(qdrant, qd_points)
    logger.info("yonetmelik_upserted no=%s n_chunks=%d", mev_no, len(qd_points))
    return len(qd_points)


async def _run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("seed_started yonetmelik n_targets=%d", len(TARGETS))
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    total = 0
    try:
        await ensure_collection(qdrant)
        async with httpx.AsyncClient(
            headers={"User-Agent": "adalet-agent/0.1 (ders projesi)"},
        ) as http_client:
            for mev_no, tur, tertip, kod, ad, dom in TARGETS:
                try:
                    n = await _seed_one(
                        http_client, embedder, qdrant,
                        mev_no, tur, tertip, kod, ad, dom,
                    )
                    total += n
                except Exception as exc:
                    logger.exception("seed_failed no=%s err=%s", mev_no, exc)
        logger.info("=" * 50)
        logger.info("YONETMELIK SEED TOPLAM: %d chunk", total)
    finally:
        await qdrant.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
