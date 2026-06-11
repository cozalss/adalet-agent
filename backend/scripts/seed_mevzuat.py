"""Mevzuat seed — Türk hukukunun temel kanunlarını mevzuat-mcp'den çekip Qdrant'a yaz.

Çekilen kanunlar (öncelik sırası):
- 6502 TKHK (Tüketicinin Korunması)
- 4857 İK   (İş Kanunu)
- 6098 TBK  (Türk Borçlar Kanunu — kira maddeleri 299-378 dahil)
- 4721 TMK  (Türk Medeni Kanunu)
- 5237 TCK  (Türk Ceza Kanunu)
- 2709 ANAYASA

Her kanun madde madde chunklanır (chunker.chunk_mevzuat).
Qdrant'a ana koleksiyon `adalet`'e payload `doc_type: "law"` ile eklenir.
Aynı koleksiyon karar+mevzuat tutar — sorguda `doc_type` filtresi ile ayırılır.

Çalıştırma:
    uv run python -m scripts.seed_mevzuat
"""

from __future__ import annotations

import asyncio
import logging
import sys

# Windows: `core.native_preload` pyarrow'u torch'tan önce yükler — BGE-M3 embedder
# warmup'ı torch sonrası segfault yapar. isort core'u retrieval'dan önce sıralar.
from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_mevzuat, sanitize_text
from retrieval.embedding import Embedder
from retrieval.mevzuat_client import KANUN_KODU_TO_NUMARA, Madde, MevzuatClient
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks

logger = logging.getLogger("scripts.seed_mevzuat")

# Çekilecek kanunlar — hepsi public, hepsi temel hukuk.
# Sprint-5 W12: 17 → 41 kanun. Her domain için 5+ ilgili kanun.
# Kapsam (CLAUDE.md §4) ile uyumlu: tuketici, isHukuku, kira, icra, trafik,
# vergi, tapu, idari domain'lerini kapsar. Alias entries (TK=KTK, KK=TPK)
# yok — her kanun bir kez seed edilir.
TARGET_LAWS: tuple[tuple[str, str], ...] = (
    # === Çekirdek özel hukuk ===
    ("TKHK", "Tüketicinin Korunması Hakkında Kanun"),
    ("IK", "İş Kanunu"),
    ("TBK", "Türk Borçlar Kanunu"),
    ("TMK", "Türk Medeni Kanunu"),
    ("TTK", "Türk Ticaret Kanunu"),
    ("ANAYASA", "Türkiye Cumhuriyeti Anayasası"),
    # === Usul kanunları ===
    ("HMK", "Hukuk Muhakemeleri Kanunu"),
    ("IYUK", "İdari Yargılama Usulü Kanunu"),
    ("KABAHAT", "Kabahatler Kanunu"),
    ("IIK", "İcra ve İflas Kanunu"),
    # === Sosyal güvenlik + iş hukuku tamamlayıcı ===
    ("SGK", "Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu"),
    ("SK", "Sendikalar ve Toplu İş Sözleşmesi Kanunu"),
    ("ISGK", "İş Sağlığı ve Güvenliği Kanunu"),
    ("DMK", "Devlet Memurları Kanunu"),
    ("EIK", "1475 sayılı İş Kanunu (kıdem tazminatı m.14)"),
    ("DIK", "Deniz İş Kanunu"),
    ("BMC", "Basın Mesleğinde Çalışanlarla Çalıştıranlar Arasındaki Münasebetlerin Tanzimi Hakkında Kanun"),
    ("OGK", "Özel Güvenlik Hizmetlerine Dair Kanun"),
    # === Tüketici + ekonomik düzen ===
    ("BK", "Bankacılık Kanunu"),
    ("SIGORTA", "Sigortacılık Kanunu"),
    ("RKHK", "Rekabetin Korunması Hakkında Kanun"),
    ("KVKK", "Kişisel Verilerin Korunması Kanunu"),
    ("OHK", "Ödeme ve Menkul Kıymet Mutabakat Sistemleri, Ödeme Hizmetleri ve Elektronik Para Kuruluşları Hakkında Kanun"),
    # === Vergi + mali ===
    ("VUK", "Vergi Usul Kanunu"),
    ("GVK", "Gelir Vergisi Kanunu"),
    ("KVK", "Kurumlar Vergisi Kanunu"),
    ("KDV", "Katma Değer Vergisi Kanunu"),
    ("OTV", "Özel Tüketim Vergisi Kanunu"),
    ("DV", "Damga Vergisi Kanunu"),
    ("MTV", "Motorlu Taşıtlar Vergisi Kanunu"),
    ("EMLAKV", "Emlak Vergisi Kanunu"),
    ("AATUHK", "Amme Alacaklarının Tahsil Usulü Hakkında Kanun"),
    ("MYK", "Kamu Mali Yönetimi ve Kontrol Kanunu"),
    ("GIBK", "Gelir İdaresi Başkanlığı Teşkilat Kanunu"),
    # === Trafik + ulaşım ===
    ("KTK", "Karayolları Trafik Kanunu"),
    ("KGK", "Karayolu Taşıma Kanunu"),
    # === Tapu + imar ===
    ("TPK", "Tapu Kanunu"),
    ("KMK", "Kat Mülkiyeti Kanunu"),
    ("IMARK", "İmar Kanunu"),
    ("KAMK", "Kamulaştırma Kanunu"),
    ("KDK", "Afet Riski Altındaki Alanların Dönüştürülmesi Hakkında Kanun"),
    # === İdari + kamu yönetimi ===
    ("IHK", "Kamu İhale Kanunu"),
    ("IHSK", "Kamu İhale Sözleşmeleri Kanunu"),
    ("DIHK", "Dilekçe Hakkının Kullanılmasına Dair Kanun"),
    ("BLDK", "Belediye Kanunu"),
    ("IOIK", "İl Özel İdaresi Kanunu"),
    ("CK", "Çevre Kanunu"),
    # === Afet + sosyal yardım ===
    ("AYK", "Umumi Hayata Müessir Afetler Dolayısiyle Alınacak Tedbirlerle Yapılacak Yardımlara Dair Kanun"),
    # === Referans — graph CITES için (kapsam-dışı ama Yargıtay kararları atıfta bulunur) ===
    ("TCK", "Türk Ceza Kanunu"),
)


async def _find_mevzuat_id(client: MevzuatClient, mevzuat_no: str) -> str | None:
    """search_mevzuat raw_text çıktısından mevzuatId'yi parse et.

    Format örnekleri:
        "- [6502] TÜKETİCİNİN KORUNMASI HAKKINDA KANUN (Kanunlar) | mevzuatId: 103101"
        "- [6098] TÜRK BORÇLAR KANUNU (Kanunlar) | mevzuatId: 103273 | RG: 2011-02-04"

    İkinci varyantta " | RG: ..." tail'ı vardır — sadece ilk numeric token'ı al.
    """
    data = await client._call_tool(
        "search_mevzuat",
        {"mevzuat_no": mevzuat_no, "mevzuat_tur": "KANUN", "page_size": 5},
    )
    text = data.get("raw_text") or ""
    for line in text.split("\n"):
        if "mevzuatId:" in line:
            tail = line.split("mevzuatId:")[-1].strip()
            # " | RG: ..." veya " | gerekceId: ..." gibi tail'ı kes; ilk token'ı al
            first_token = tail.split("|", 1)[0].strip()
            # Whitespace ile de bölünebilir
            first_token = first_token.split()[0] if first_token else ""
            # Sadece numeric id'leri kabul et
            if first_token.isdigit():
                return first_token
    return None
    return None


async def _fetch_full_content(client: MevzuatClient, mevzuat_id: str) -> str:
    """get_mevzuat_content çıktısı raw_text olarak gelir."""
    data = await client._call_tool(
        "get_mevzuat_content",
        {"mevzuat_id": mevzuat_id},
    )
    return data.get("raw_text") or data.get("markdown_content") or ""


def _build_maddeler(
    kanun_kodu: str,
    kanun_numarasi: str,
    kanun_adi: str,
    full_text: str,
    mevzuat_id: str,
) -> list[Madde]:
    """chunker.chunk_mevzuat ile madde madde böl, Madde dataclass'a sar."""
    full_text = sanitize_text(full_text)
    raw_chunks = chunk_mevzuat(full_text)
    source_url = f"https://mevzuat.gov.tr/mevzuat?MevzuatNo={kanun_numarasi}&MevzuatTur=1"

    maddeler: list[Madde] = []
    for c in raw_chunks:
        madde_no = c.metadata.get("madde_no")
        if not madde_no:
            continue
        if len(c.text) < 30:
            continue
        # Başlık ilk satır olabilir
        first_line = c.text.split("\n", 1)[0].strip()
        baslik = first_line if len(first_line) < 200 else None
        maddeler.append(
            Madde(
                kanun_kodu=kanun_kodu,
                kanun_numarasi=kanun_numarasi,
                kanun_adi=kanun_adi,
                madde_no=int(madde_no),
                baslik=baslik,
                metin=c.text,
                source_url=source_url,
                # P8: chunker artık Ek/Geçici madde başlıklarını ayırıyor; tur
                # payload'a yazılır → id m-VUK-ek-11, fetch/verify tur-bilinçli.
                madde_tur=c.metadata.get("madde_tur", "madde"),
            )
        )
    return maddeler


async def _seed_one_law(
    mevzuat_client: MevzuatClient,
    embedder: Embedder,
    qdrant,
    kanun_kodu: str,
    kanun_adi: str,
) -> int:
    """Tek bir kanunu çek + embed + Qdrant'a yaz. Madde sayısını döndür."""
    numara = KANUN_KODU_TO_NUMARA[kanun_kodu]
    logger.info("law_started %s (%s)", kanun_kodu, numara)

    mevzuat_id = await _find_mevzuat_id(mevzuat_client, numara)
    if not mevzuat_id:
        logger.warning("law_id_not_found %s", numara)
        return 0
    logger.info("law_id_found %s -> %s", numara, mevzuat_id)

    text = await _fetch_full_content(mevzuat_client, mevzuat_id)
    logger.info("law_content_fetched %s len=%d", kanun_kodu, len(text))

    maddeler = _build_maddeler(kanun_kodu, numara, kanun_adi, text, mevzuat_id)
    if not maddeler:
        logger.warning("no_maddeler_parsed %s", kanun_kodu)
        return 0
    logger.info("law_maddeler_parsed %s count=%d", kanun_kodu, len(maddeler))

    # Embed batch
    texts = [m.metin for m in maddeler]
    out = await asyncio.to_thread(embedder.encode, texts, 8)

    points = [
        ChunkPoint(
            id=m.id,
            dense_vector=dense,
            sparse_indices=sparse[0],
            sparse_values=sparse[1],
            payload={**m.to_payload(), "text": m.metin},
        )
        for m, dense, sparse in zip(maddeler, out.dense, out.sparse)
    ]

    await upsert_chunks(qdrant, points)
    logger.info("law_upserted %s madde_count=%d", kanun_kodu, len(points))
    return len(points)


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("mevzuat_seed_started laws=%d", len(TARGET_LAWS))

    logger.info("warming_embedder")
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    try:
        await ensure_collection(qdrant)

        async with MevzuatClient() as mevzuat_client:
            total_maddeler = 0
            for kanun_kodu, kanun_adi in TARGET_LAWS:
                try:
                    count = await _seed_one_law(
                        mevzuat_client, embedder, qdrant, kanun_kodu, kanun_adi
                    )
                    total_maddeler += count
                except Exception as exc:
                    logger.exception("law_seed_failed %s: %s", kanun_kodu, exc)

            logger.info("=" * 60)
            logger.info("MEVZUAT TOPLAM: %d madde", total_maddeler)
    finally:
        await qdrant.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
