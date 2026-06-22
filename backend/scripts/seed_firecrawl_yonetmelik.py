"""Firecrawl SEARCH + scrape ile YÖNETMELİK çek → chunk → embed → Qdrant (korpusun en büyük boşluğu).

Korpusta ~128 yönetmelik chunk'ı var (kanun 7917). Pratik soruların çoğu yönetmelikte cevaplanır
(kanun 'zorundadır' der, yönetmelik 'nasıl/ne sıklıkla/hangi belge' der). Bu script o boşluğu doldurur.

Akış: Firecrawl /search ile resmi mevzuat.gov.tr Tur=7 URL'ini BUL (MevzuatNo elle gerekmez) →
scrape → extract_law_body (bold-sıyır) → chunk_mevzuat → embed → upsert. Madde.id deterministik
(m-YON_X-N) → idempotent. Kodlar agents/config.py DOMAIN_TO_KANUN_KODU'ya kaydedilmeli (boost).

Kullanım:  LLM_MODE=mock uv run python -m scripts.seed_firecrawl_yonetmelik [--only YON_ISG_RISK]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path

_ENV = Path(".env")
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_mevzuat, sanitize_text
from retrieval.embedding import Embedder
from retrieval.firecrawl_client import scrape_legal_url, search_mevzuat_url
from retrieval.mevzuat_client import Madde
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks
from scripts.seed_firecrawl_mevzuat import extract_law_body

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("seed_yon_fc")

# 8 domaine yayılı önemli yönetmelikler. (q=arama sorgusu, kodu, adi, domain). Search MevzuatNo'yu bulur.
REGULATIONS: list[dict] = [
    # --- iş ---
    {"q": "İş Sağlığı ve Güvenliği Risk Değerlendirmesi Yönetmeliği", "kodu": "YON_ISG_RISK", "adi": "İSG Risk Değerlendirmesi Yönetmeliği", "domain": "isHukuku"},
    {"q": "İş Sağlığı ve Güvenliği Hizmetleri Yönetmeliği", "kodu": "YON_ISG_HIZMET", "adi": "İSG Hizmetleri Yönetmeliği", "domain": "isHukuku"},
    {"q": "Çalışanların İş Sağlığı ve Güvenliği Eğitimlerinin Usul ve Esasları Hakkında Yönetmelik", "kodu": "YON_ISG_EGITIM", "adi": "Çalışanların İSG Eğitimleri Yönetmeliği", "domain": "isHukuku"},
    {"q": "İş Kanununa İlişkin Fazla Çalışma ve Fazla Sürelerle Çalışma Yönetmeliği", "kodu": "YON_FAZLA", "adi": "Fazla Çalışma Yönetmeliği", "domain": "isHukuku"},
    {"q": "Yıllık Ücretli İzin Yönetmeliği", "kodu": "YON_YILLIK", "adi": "Yıllık Ücretli İzin Yönetmeliği", "domain": "isHukuku"},
    {"q": "İş Kanununa İlişkin Çalışma Süreleri Yönetmeliği", "kodu": "YON_CALISMA", "adi": "Çalışma Süreleri Yönetmeliği", "domain": "isHukuku"},
    {"q": "Kadın Çalışanların Gece Postalarında Çalıştırılması Yönetmeliği", "kodu": "YON_GECE", "adi": "Kadın Çalışanların Gece Postaları Yönetmeliği", "domain": "isHukuku"},
    {"q": "Postalar Halinde İşçi Çalıştırılarak Yürütülen İşlerde Çalışmalara İlişkin Yönetmelik", "kodu": "YON_POSTA", "adi": "Postalar Halinde Çalışma Yönetmeliği", "domain": "isHukuku"},
    # --- tüketici ---
    {"q": "Fiyat Etiketi Yönetmeliği tüketici", "kodu": "YON_ETIKET", "adi": "Fiyat Etiketi Yönetmeliği", "domain": "tuketici"},
    {"q": "Ön Ödemeli Konut Satışları Hakkında Yönetmelik", "kodu": "YON_ONODEME", "adi": "Ön Ödemeli Konut Satış Yönetmeliği", "domain": "tuketici"},
    {"q": "Devre Tatil ve Uzun Süreli Tatil Hizmeti Sözleşmeleri Yönetmeliği", "kodu": "YON_DEVRE", "adi": "Devre Tatil Yönetmeliği", "domain": "tuketici"},
    {"q": "Abonelik Sözleşmeleri Yönetmeliği tüketici", "kodu": "YON_ABONELIK", "adi": "Abonelik Sözleşmeleri Yönetmeliği", "domain": "tuketici"},
    {"q": "Taksitle Satış Sözleşmeleri Hakkında Yönetmelik", "kodu": "YON_TAKSIT", "adi": "Taksitle Satış Yönetmeliği", "domain": "tuketici"},
    {"q": "Paket Tur Sözleşmeleri Yönetmeliği", "kodu": "YON_PAKET", "adi": "Paket Tur Sözleşmeleri Yönetmeliği", "domain": "tuketici"},
    {"q": "İşyeri Dışında Kurulan Sözleşmeler Yönetmeliği tüketici", "kodu": "YON_ISYERIDISI", "adi": "İşyeri Dışında Kurulan Sözleşmeler Yönetmeliği", "domain": "tuketici"},
    # --- trafik ---
    {"q": "Karayolları Trafik Yönetmeliği", "kodu": "YON_TRAFIK", "adi": "Karayolları Trafik Yönetmeliği", "domain": "trafik"},
    {"q": "Araç Muayene İstasyonlarının Açılması Yönetmeliği", "kodu": "YON_MUAYENE", "adi": "Araç Muayene Yönetmeliği", "domain": "trafik"},
    {"q": "Karayolu Taşıma Yönetmeliği", "kodu": "YON_TASIMA", "adi": "Karayolu Taşıma Yönetmeliği", "domain": "trafik"},
    # --- idari ---
    {"q": "Planlı Alanlar İmar Yönetmeliği", "kodu": "YON_IMAR", "adi": "Planlı Alanlar İmar Yönetmeliği", "domain": "idari"},
    {"q": "Çevresel Etki Değerlendirmesi Yönetmeliği ÇED", "kodu": "YON_CED", "adi": "ÇED Yönetmeliği", "domain": "idari"},
    {"q": "Mal Alımı İhaleleri Uygulama Yönetmeliği kamu ihale", "kodu": "YON_IHALE_MAL", "adi": "Mal Alımı İhaleleri Uygulama Yönetmeliği", "domain": "idari"},
    {"q": "Hizmet Alımı İhaleleri Uygulama Yönetmeliği kamu ihale", "kodu": "YON_IHALE_HIZMET", "adi": "Hizmet Alımı İhaleleri Uygulama Yönetmeliği", "domain": "idari"},
    {"q": "Yapım İşleri İhaleleri Uygulama Yönetmeliği kamu ihale", "kodu": "YON_IHALE_YAPIM", "adi": "Yapım İşleri İhaleleri Uygulama Yönetmeliği", "domain": "idari"},
    {"q": "Mezarlık Yerlerinin İnşaası ile Cenaze Nakil ve Defin İşlemleri Yönetmeliği", "kodu": "YON_DEFIN", "adi": "Cenaze ve Defin İşlemleri Yönetmeliği", "domain": "idari"},
    # --- tapu / kira ---
    {"q": "Tapu Sicili Tüzüğü", "kodu": "YON_TAPU_SICIL", "adi": "Tapu Sicili Tüzüğü", "domain": "tapu"},
    {"q": "Kat Mülkiyeti Kanununun Uygulanmasına İlişkin Yönetmelik", "kodu": "YON_KMK", "adi": "Kat Mülkiyeti Yönetmeliği", "domain": "kira"},
    {"q": "Yapı Kayıt Belgesi Verilmesine İlişkin Usul ve Esaslar imar barışı", "kodu": "YON_YAPIKAYIT", "adi": "Yapı Kayıt Belgesi Usul ve Esasları", "domain": "tapu"},
    # --- icra / vergi ---
    {"q": "İcra ve İflas Kanunu Yönetmeliği", "kodu": "YON_ICRA", "adi": "İcra ve İflas Kanunu Yönetmeliği", "domain": "icra"},
    {"q": "Vergi Usul Kanunu Genel Tebliği elektronik defter usul esas", "kodu": "YON_VUK", "adi": "VUK Uygulama Yönetmeliği", "domain": "vergi"},
]


def _build_maddeler(kodu: str, adi: str, source_url: str, full_text: str) -> list[Madde]:
    """chunk_mevzuat ile böl, Madde'ye sar — source_url SCRAPE edilen gerçek mevzuat URL'i."""
    raw = chunk_mevzuat(sanitize_text(full_text), subchunk=False)
    numara = (re.search(r"MevzuatNo=(\d+)", source_url) or [None, ""])[1] if "MevzuatNo=" in source_url else ""
    out: list[Madde] = []
    for c in raw:
        mn = c.metadata.get("madde_no")
        if not mn or len(c.text) < 30:
            continue
        first = c.text.split("\n", 1)[0].strip()
        out.append(Madde(
            kanun_kodu=kodu, kanun_numarasi=numara, kanun_adi=adi, madde_no=int(mn),
            baslik=(first if len(first) < 200 else None), metin=c.text,
            source_url=source_url, madde_tur=c.metadata.get("madde_tur", "madde"),
        ))
    return out


async def seed_one(reg: dict, embedder: Embedder, qdrant) -> int:
    logger.info("search %s ...", reg["kodu"])
    url = await search_mevzuat_url(reg["q"])
    if not url:
        logger.warning("search_miss %s (%s) — mevzuat URL bulunamadı", reg["kodu"], reg["q"][:40])
        return 0
    logger.info("  url=%s", url)
    md = await scrape_legal_url(url, timeout_s=70)
    if not md:
        logger.warning("scrape_empty %s", reg["kodu"])
        return 0
    maddeler = _build_maddeler(reg["kodu"], reg["adi"], url, extract_law_body(md))
    if not maddeler:
        logger.warning("no_maddeler %s (markdown=%d) — parse edilemedi", reg["kodu"], len(md))
        return 0

    out = await asyncio.to_thread(embedder.encode, [m.metin for m in maddeler], 8)
    points = [
        ChunkPoint(id=m.id, dense_vector=d, sparse_indices=s[0], sparse_values=s[1],
                   payload={**m.to_payload(), "text": m.metin})
        for m, d, s in zip(maddeler, out.dense, out.sparse)
    ]
    await upsert_chunks(qdrant, points)
    logger.info("✓ upserted %s madde=%d  (%s)", reg["kodu"], len(points), reg["domain"])
    return len(points)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()
    regs = REGULATIONS
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        regs = [r for r in regs if r["kodu"] in want]

    logger.info("warming_embedder...")
    embedder = Embedder()
    qdrant = get_client()
    await ensure_collection(qdrant)

    total = ok = 0
    for reg in regs:
        try:
            n = await seed_one(reg, embedder, qdrant)
            total += n
            ok += 1 if n else 0
        except Exception as exc:
            logger.warning("reg_failed %s: %s", reg["kodu"], type(exc).__name__)
    logger.info("=== BİTTİ: %d/%d yönetmelik, toplam %d madde upserted ===", ok, len(regs), total)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
