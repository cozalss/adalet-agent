"""Faz-4 adım 1 — GERÇEK Türkçe-hukuk BEIR datasetlerini (sorgu, pozitif) çiftine indir.

newmindai/caselaw-retrieval (Yargıtay HGK sivil) + newmindai/regulation-retrieval
(GİB özelge: vergi/idari) — her ikisi de public, CC-BY-4.0, temiz BEIR yapısı
(corpus{_id,text} / queries{_id,text} / qrels{query-id,corpus-id,score}).

Üretir:
  data/reranker/pairs.jsonl   — {query_id, query, pos_id, pos_text, domain, source}
  data/reranker/corpus.jsonl  — {id, text, source}  (hard-negative madenleme havuzu)

KAPSAM-DIŞI (ceza/aile) çiftler ELENİR (_core.is_out_of_scope — kırmızı çizgi).
Pozitif metinler GERÇEK kararlardan; hiçbir şey uydurulmaz.

Kullanım: cd backend && uv run python -m scripts.reranker.load_sources [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from scripts.reranker._core import QAPair, is_out_of_scope, tag_domain

# (HF adı, qrels config adı, kaynak etiketi). Şema her ikisinde aynı (BEIR).
_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("newmindai/caselaw-retrieval", "qrels", "yargitay"),
    ("newmindai/regulation-retrieval", "default", "ozelge"),
)
_OUT_DIR = Path("data/reranker")


def _load_config(name: str, config: str) -> list[dict]:
    """Tek bir HF config'i tam yükle → satır listesi."""
    from datasets import load_dataset

    ds = load_dataset(name, config)
    split = next(iter(ds.keys()))  # genelde 'train' / 'corpus' / 'queries'
    return list(ds[split])


def load_source_pairs(
    name: str, qrels_config: str, source: str, limit: int | None = None,
) -> tuple[list[QAPair], dict[str, str]]:
    """Bir BEIR datasetini (QAPair listesi, corpus_id→text) olarak yükle + filtrele."""
    corpus = {r["_id"]: r["text"] for r in _load_config(name, "corpus")}
    queries = {r["_id"]: r["text"] for r in _load_config(name, "queries")}
    qrels = _load_config(name, qrels_config)

    pairs: list[QAPair] = []
    for row in qrels:
        if float(row.get("score", 0)) <= 0:
            continue
        qid, cid = row["query-id"], row["corpus-id"]
        q_text, pos_text = queries.get(qid), corpus.get(cid)
        if not q_text or not pos_text:
            continue
        # KIRMIZI ÇİZGİ: ceza/aile içerenleri ELE (sorgu VEYA pozitif metinden).
        if is_out_of_scope(q_text) or is_out_of_scope(pos_text):
            continue
        pairs.append(QAPair(
            query_id=qid, query=q_text, pos_id=cid, pos_text=pos_text,
            domain=tag_domain(f"{q_text} {pos_text[:400]}"), source="formal",
        ))
        if limit and len(pairs) >= limit:
            break
    return pairs, corpus


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(limit: int | None = None) -> None:
    all_pairs: list[QAPair] = []
    corpus_rows: list[dict] = []
    for name, qrels_config, source in _SOURCES:
        print(f"[*] {name} yükleniyor...", flush=True)
        pairs, corpus = load_source_pairs(name, qrels_config, source, limit)
        all_pairs.extend(pairs)
        corpus_rows.extend({"id": cid, "text": txt, "source": source}
                           for cid, txt in corpus.items()
                           if not is_out_of_scope(txt))
        kept = sum(1 for d in {p.domain for p in pairs})
        print(f"    {len(pairs)} çift ({kept} farklı alan), {len(corpus)} corpus belgesi")

    _write_jsonl(_OUT_DIR / "pairs.jsonl", [asdict(p) for p in all_pairs])
    _write_jsonl(_OUT_DIR / "corpus.jsonl", corpus_rows)
    by_domain: dict[str, int] = {}
    for p in all_pairs:
        by_domain[p.domain] = by_domain.get(p.domain, 0) + 1
    print(f"[+] {len(all_pairs)} çift -> {_OUT_DIR/'pairs.jsonl'}")
    print(f"[+] {len(corpus_rows)} negatif-havuz belgesi -> {_OUT_DIR/'corpus.jsonl'}")
    print(f"    alan dağılımı: {dict(sorted(by_domain.items(), key=lambda x: -x[1]))}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="TR-hukuk BEIR → reranker pairs")
    parser.add_argument("--limit", type=int, default=None,
                        help="Kaynak başına en fazla N çift (hızlı deneme için)")
    args = parser.parse_args()
    main(limit=args.limit)
