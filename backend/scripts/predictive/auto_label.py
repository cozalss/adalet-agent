"""Otomatik etiketleme — Yargıtay kararlarından dava-sonucu eğitim verisi (CPU).

Üye4 tezi (BERT-TR dava sonucu tahmini) için silver-label korpusu üretir.
Fine-tune GPU ister; bu veri pipeline'ı TAMAMEN CPU'da koşar.

Yöntem (DRY — labeling mantığı `predictive/inference.py`'den yeniden kullanılır):
  1. HF parquet'ten tam karar metni (seed_hf_yargitay ile aynı kaynak).
  2. Chamber → in-scope domain (CEZA daireleri atlanır).
  3. HÜKÜM bölümünü izole et → `_classify_outcome` ile kabul/ret/kısmi sinyali.

KRİTİK — label leakage önleme: BERT'in girdisi (`input_text`) HÜKÜM bölümünü
İÇERMEZ (yalnız olay + gerekçe). Label hükümden gelir. Model tam metni görseydi
hükmü okuyup cevabı kopyalardı (sahte %99 accuracy) → bu split metodolojik olarak
zorunludur. Tez §'ında "leak-free silver supervision" olarak raporlanır.

ÖNEMLİ: Etiketler HEURISTIC (~%70, README Aşama-1) — "silver". Eval için
insan-doğrulanmış altın subset (200 vaka, Cohen's kappa) AYRI gerekir; bu script
training-set üretir, gold-set değil.

Kullanım:
    uv run python -m scripts.predictive.auto_label --shards 0 --cap-per-class 1000
    uv run python -m scripts.predictive.auto_label --shards 0,1,2 --out data/predictive/labeled_v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

# Windows: pyarrow'u torch'tan önce yükle (seed scriptleriyle aynı guard).
from core import native_preload  # noqa: F401

# DRY — labeling çekirdeği inference.py'de (test'li). Private ama bilinçli reuse:
# inference modülü bu heuristic'i "Aşama-1 baseline" olarak belgeliyor.
from predictive.inference import (
    _HUKUM_HEADER_RE,
    _HUKUM_TAIL_CHARS,
    _classify_outcome,
)
from retrieval.turkish_text import tr_lower
from scripts.seed_hf_yargitay import REPO, _detect_chamber_domain

logger = logging.getLogger("scripts.predictive.auto_label")

_MIN_INPUT_LEN = 200    # hüküm çıktıktan sonra anlamlı kalan en az metin
_EXCERPT_CHARS = 400    # hüküm excerpt (denetlenebilirlik için saklanır)


@dataclass(frozen=True, slots=True)
class LabelRecord:
    """Tek bir karar için leak-free eğitim örneği."""

    doc_id: str
    chamber: str
    domain: str
    label: str              # kazandi | kaybetti | kismi
    input_text: str         # HÜKÜM HARİÇ (olay + gerekçe) — model girdisi
    hukum_excerpt: str      # label kaynağı (denetim için; eğitimde KULLANILMAZ)


def _split_hukum(text: str) -> tuple[str, str]:
    """Karar metnini (hüküm_öncesi, hüküm) olarak ayır.

    `_isolate_hukum`'un aksine İKİ parçayı birden döndürür: öncesi model girdisi
    (leak-free), sonrası label kaynağı. Aynı eşik/regex'i kullanır (tutarlılık).
    """
    text_low = tr_lower(text)
    m = _HUKUM_HEADER_RE.search(text_low)
    if m:
        return text[: m.start()], text_low[m.end():]
    # Başlık yok → son _HUKUM_TAIL_CHARS hüküm sayılır, öncesi girdi.
    return text[:-_HUKUM_TAIL_CHARS], text_low[-_HUKUM_TAIL_CHARS:]


def build_label_record(text: str, doc_id: str) -> LabelRecord | None:
    """Tek karar metni → leak-free etiketli kayıt (saf fonksiyon, test edilebilir).

    None döner: scope-dışı daire, sinyal-yok hüküm, ya da girdi çok kısa.
    """
    chamber, domain = _detect_chamber_domain(text)
    if not domain or not chamber:
        return None
    input_text, hukum_low = _split_hukum(text)
    if len(input_text) < _MIN_INPUT_LEN:
        return None
    label = _classify_outcome(hukum_low)
    if label is None:
        return None  # net sonuç sinyali yok → silver-label üretme (gürültü ekleme)
    return LabelRecord(
        doc_id=doc_id, chamber=chamber, domain=domain, label=label,
        input_text=input_text.strip(),
        hukum_excerpt=hukum_low[:_EXCERPT_CHARS].strip(),
    )


def _run(args: argparse.Namespace) -> int:
    shards = [int(s) for s in args.shards.split(",")]
    cap = args.cap_per_class
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    per_class: dict[str, int] = {}          # global label sayacı
    per_domain_class: dict[tuple[str, str], int] = {}
    seen: set[str] = set()
    n_docs = n_written = n_skipped = 0

    logger.info("auto_label_started shards=%s cap_per_class=%d out=%s", shards, cap, out_path)
    with out_path.open("w", encoding="utf-8") as fh:
        for shard_idx in shards:
            fp = hf_hub_download(
                repo_id=REPO,
                filename=f"data/train-{shard_idx:05d}-of-00009.parquet",
                repo_type="dataset",
            )
            logger.info("shard_loaded idx=%d", shard_idx)
            pf = pq.ParquetFile(fp)
            for batch in pf.iter_batches(batch_size=1000):
                texts = batch.column("text").to_pylist()
                ids = batch.column("id").to_pylist()
                for txt, did in zip(texts, ids):
                    n_docs += 1
                    if not txt or len(txt) < 200:
                        continue
                    sid = str(did)
                    if sid in seen:
                        continue
                    seen.add(sid)
                    rec = build_label_record(txt, f"h-{sid}")
                    if rec is None:
                        n_skipped += 1
                        continue
                    # Sınıf-dengesi için class başına cap (dataset bias'ı sınırla).
                    if per_class.get(rec.label, 0) >= cap:
                        continue
                    fh.write(json.dumps({
                        "doc_id": rec.doc_id, "chamber": rec.chamber,
                        "domain": rec.domain, "label": rec.label,
                        "input_text": rec.input_text, "hukum_excerpt": rec.hukum_excerpt,
                    }, ensure_ascii=False) + "\n")
                    per_class[rec.label] = per_class.get(rec.label, 0) + 1
                    per_domain_class[(rec.domain, rec.label)] = (
                        per_domain_class.get((rec.domain, rec.label), 0) + 1
                    )
                    n_written += 1
                    if n_written % 500 == 0:
                        logger.info("progress written=%d per_class=%s", n_written, per_class)
                if all(per_class.get(c, 0) >= cap for c in ("kazandi", "kaybetti", "kismi")):
                    logger.info("all_classes_capped early-stop")
                    break

    logger.info("=" * 56)
    logger.info("AUTO-LABEL: %d karar tarandı, %d etiketlendi, %d atlandı",
                n_docs, n_written, n_skipped)
    logger.info("Sınıf dağılımı: %s", per_class)
    for (dom, lbl), n in sorted(per_domain_class.items()):
        logger.info("  %s/%s: %d", dom, lbl, n)
    logger.info("Çıktı: %s", out_path)
    logger.info("NOT: silver-label (heuristic ~%%70). Gold eval-set ayrı gerekir "
                "(insan-doğrulamalı 200 vaka, Cohen's kappa).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.predictive.auto_label")
    parser.add_argument("--shards", default="0", help="virgüllü: 0 veya 0,1,2 (max 0..8)")
    parser.add_argument("--cap-per-class", type=int, default=1000,
                        help="label başına maksimum örnek (sınıf dengesi)")
    parser.add_argument("--out", default="data/predictive/labeled_v1.jsonl")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
