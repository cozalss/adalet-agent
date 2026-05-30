"""Draft (hukuki cevap) KALİTE değerlendirmesi — full-pipeline, gerçek-LLM uyumlu.

`draft.tr.txt`'in dayattığı 4 kalite boyutunu ölçer:

  1. Kısa cevap formatı : cevap "**Kısa cevap:**" ile mi açılıyor (zorunlu format)
  2. Türkçe saflığı      : Çince/Kiril/Arapça vb. yabancı harf SIZINTISI oranı
                           (bozuk Türkçe tespiti — purity = 1 - yabancı/toplam-harf)
  3. Kaynak bağı         : [src: <id>] etiketi taşıyan cümle oranı (kaynaksız
                           iddia düşük olmalı; draft.py kuralı)
  4. Cevap uzunluğu      : kelime sayısı — draft.tr.txt hedefi 160-220 kelime

Akış: her soru için `graph.ainvoke(make_initial_state(soru))` çalıştırılır →
final `response` (yoksa state'teki `draft_response`) alınır → finalize'ın eklediği
"---\\n**Kaynaklar:**" + disclaimer bloğu kesilir → saf metrik fonksiyonları ölçer.

Önemli: MockLLM (default) canned "[MOCK]..." cevabı döndürür → metrikler
ANLAMSIZdır (kısa-cevap False, purity yapay). Harness yine de ÇÖKMEDEN koşar
(smoke). Gerçek ölçüm için Qdrant + Qwen ile:

    LLM_MODE=llamacpp uv run python -m eval.draft_quality

MockLLM smoke (Qdrant gerekmeyebilir; gerekirse vaka izole hata olarak raporlanır):

    LLM_MODE=mock uv run python -m eval.draft_quality

N override: env `DRAFT_QUALITY_N` (default 20).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# draft.py'deki kaynak-etiketi + cümle-ayraç regex'lerini YENİDEN YAZMA, İMPORT ET.
# (draft import'u torch çekmez — sadece regex; native_preload yine de torch'tan
#  önce gelir çünkü graph/retrieval lazy import'ları main() içinde.)
from agents.nodes.draft import _SENT_SPLIT_RE, _SRC_TAG_RE
from core import native_preload  # noqa: F401  — pyarrow'u torch'tan önce yükle (Windows)

BENCH_DIR = Path(__file__).parent.parent / "data" / "eval_benchmark"
RUNS_DIR = Path(__file__).parent / "runs"

DEFAULT_N = 20
# draft.tr.txt hedef aralığı (madde "Uzunluk ve üslup").
TARGET_WORD_MIN = 160
TARGET_WORD_MAX = 220
# "**Kısa cevap:**" cevabın EN BAŞINDA olmalı; baş bölgeyi bu pencerede ara.
SHORT_ANSWER_HEAD_CHARS = 120

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Saf metrik fonksiyonları (LLM/Qdrant'sız — ayrı ayrı test edilebilir)
# --------------------------------------------------------------------------- #

# finalize_node sonu: "...cevap\n\n---\n**Kaynaklar:**\n- ...\n\n<disclaimer>".
# Kalite ölçümünde sadece LLM'in ÜRETTİĞİ gövdeyi istiyoruz; kaynak listesi +
# disclaimer LLM çıktısı değil, finalize'ın eklediği boilerplate → kelime sayımı
# ve src-coverage'ı şişirmesin diye kesilir.
_SOURCES_BLOCK_RE = re.compile(r"\n+-{2,}\s*\n+\*\*Kaynaklar:\*\*", re.IGNORECASE)
# Disclaimer / boilerplate cümleler src-coverage paydasından düşülür (iddia değil).
_BOILERPLATE_MARKERS = (
    "avukata danış",
    "bilgilendirme amaç",
    "hukuki tavsiye değil",
    "kesin işlem için",
    "bir avukattan destek",
)
# Türkçe + ASCII izinli harf aralığı; bunun DIŞINDAKİ harfler "yabancı" sayılır.
_TURKISH_LETTER_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü]")
# Yabancı yazı sistemleri: CJK, Kiril, Arapça, Hangul, Hiragana/Katakana, İbranice.
_FOREIGN_SCRIPT_RE = re.compile(
    r"[一-鿿"   # CJK Unified Ideographs (Çince/Japonca/Korece)
    r"぀-ヿ"    # Hiragana + Katakana
    r"가-힯"    # Hangul (Korece)
    r"Ѐ-ӿ"    # Kiril
    r"؀-ۿ"    # Arapça
    r"֐-׿"    # İbranice
    r"]"
)


def strip_boilerplate_block(text: str) -> str:
    """finalize'ın eklediği '---\\n**Kaynaklar:**...' + disclaimer kuyruğunu kes.

    LLM'in ürettiği cevap gövdesini izole eder. Blok yoksa metin aynen döner.
    """
    match = _SOURCES_BLOCK_RE.search(text)
    return text[: match.start()].rstrip() if match else text.strip()


def has_short_answer(text: str) -> bool:
    """Cevap '**Kısa cevap:**' (veya 'Kısa cevap:') ile mi açılıyor.

    draft.tr.txt: ilk satır MUTLAKA bu etiketle başlamalı. Baş ~120 karakterde
    arar; markdown yıldızları/önek boşlukları tolere edilir, casefold ile büyük/
    küçük harf duyarsız.
    """
    head = text[:SHORT_ANSWER_HEAD_CHARS]
    normalized = head.replace("*", "").casefold()
    return "kısa cevap:" in normalized


def turkish_purity(text: str) -> float:
    """Yabancı-harf sızıntısı ölçer: purity = 1 - (yabancı_harf / toplam_harf).

    Toplam harf = Türkçe/ASCII harfleri + yabancı yazı-sistemi harfleri.
    Rakam, noktalama, boşluk, markdown sembolleri sayılmaz (harf değil).
    Harf hiç yoksa 1.0 (boş/sembolik metin "kirli" sayılmaz). 1.0 = saf Türkçe.
    """
    turkish = len(_TURKISH_LETTER_RE.findall(text))
    foreign = len(_FOREIGN_SCRIPT_RE.findall(text))
    total = turkish + foreign
    if total == 0:
        return 1.0
    return round(1.0 - (foreign / total), 4)


def _is_meaningful_sentence(clean: str) -> bool:
    """src-coverage paydasına girecek cümle mi: yeterince uzun, iddia, boilerplate değil."""
    if len(clean) < 30:
        return False
    if clean.endswith("?"):
        return False
    low = clean.casefold()
    return not any(marker in low for marker in _BOILERPLATE_MARKERS)


def src_tag_coverage(text: str) -> float:
    """Anlamlı cümlelerin kaçında [src: <id>] etiketi var (oran).

    Cümleler draft.py'nin _SENT_SPLIT_RE'siyle ayrılır; disclaimer/boilerplate ve
    çok kısa/soru cümleleri payda-dışı bırakılır (draft.py:_extract_claims mantığı).
    Anlamlı cümle yoksa 0.0 (ölçülecek iddia yok = kaynak bağı gösterilemedi).
    """
    meaningful = 0
    tagged = 0
    for sent in _SENT_SPLIT_RE.split(text):
        has_tag = bool(_SRC_TAG_RE.search(sent))
        clean = _SRC_TAG_RE.sub("", sent).strip()
        if not _is_meaningful_sentence(clean):
            continue
        meaningful += 1
        if has_tag:
            tagged += 1
    if meaningful == 0:
        return 0.0
    return round(tagged / meaningful, 4)


def word_count(text: str) -> int:
    """Kaynak etiketleri çıkarıldıktan sonraki kelime sayısı (whitespace bölünmüş)."""
    clean = _SRC_TAG_RE.sub("", text)
    return len(clean.split())


def length_in_target(wc: int) -> bool:
    """Kelime sayısı draft.tr.txt hedef aralığında mı (160-220, sınırlar dahil)."""
    return TARGET_WORD_MIN <= wc <= TARGET_WORD_MAX


# Düzgün biten cümle: terminal noktalama (. ! ? ) veya kapanış (kaynak etiketi/parantez).
_PROPER_END_RE = re.compile(r"[.!?…»)\]]\s*$|\[src:[^\]]+\]\s*$")


def is_truncated(text: str) -> bool:
    """Cevap LLM token limiti nedeniyle ortada kesilmiş mi (heuristik).

    Sinyal: gövde anlamlı bir cümle sonu noktalamasıyla bitmiyorsa (örn. cümle
    ortasında, yarım kelimede biterse) token cap'e takılmış demektir. tokens_out
    == LLM_MAX_TOKENS doğrudan ölçülemediğinden (graph LLM'i sarmalıyor) metin-
    tabanlı proxy. Boş gövde truncation sayılmaz (ayrı hata).
    """
    body = strip_boilerplate_block(text).rstrip()
    if not body:
        return False
    return not bool(_PROPER_END_RE.search(body))


def measure(text: str) -> dict:
    """Tek cevap için 4 boyutlu kalite ölçümü (boilerplate kuyruğu kesilmiş)."""
    body = strip_boilerplate_block(text)
    wc = word_count(body)
    return {
        "has_short_answer": has_short_answer(body),
        "turkish_purity": turkish_purity(body),
        "src_coverage": src_tag_coverage(body),
        "word_count": wc,
        "length_in_target": length_in_target(wc),
        "is_truncated": is_truncated(text),
        "chars": len(body),
    }


# --------------------------------------------------------------------------- #
# Harness (graph koşturma + agregasyon + rapor)
# --------------------------------------------------------------------------- #


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent.parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "no-git"


def _load_jsonl(name: str) -> list[dict]:
    path = BENCH_DIR / name
    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _eval_n() -> int:
    raw = os.environ.get("DRAFT_QUALITY_N", str(DEFAULT_N))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_N


def _answer_text(state: dict) -> str:
    """Ölçülecek metin: final `response`, yoksa ham `draft_response`."""
    return (state.get("response") or state.get("draft_response") or "").strip()


def _warm_retrieval_before_llm() -> None:
    """Gerçek-LLM modunda embedder/reranker'ı Qwen'den ÖNCE yükle (Windows segfault guard).

    FlagEmbedding/torch, llama_cpp yüklendikten SONRA ilk kez init edilirse
    Windows'ta EXIT 139 oluyor (bkz. verify_ablation._warm_retrieval_before_llm).
    Mock modda gereksiz → çağrılmaz.
    """
    with contextlib.suppress(Exception):
        from retrieval.embedding import Embedder
        Embedder().encode(["ısınma"], return_colbert=False)
    with contextlib.suppress(Exception):
        from retrieval.reranker import get_reranker
        _ = get_reranker()._model


async def _run_case(graph, case: dict) -> dict:
    """Tek vaka: graph'ı koştur, cevabı ölç. Çökerse vaka-izole hata satırı döner."""
    from agents.graph import make_initial_state

    qid = case["id"]
    question = case["soru"]
    t0 = time.time()
    try:
        state = await graph.ainvoke(make_initial_state(question))
    except Exception as exc:  # her vakayı izole et — biri patlarsa diğerleri koşsun
        return {"id": qid, "question": question, "error": str(exc)[:160],
                "elapsed_ms": int((time.time() - t0) * 1000)}
    metrics = measure(_answer_text(state))
    metrics.update({
        "id": qid,
        "question": question,
        "verdict": state.get("debate_verdict", "?"),
        "confidence": round(float(state.get("confidence", 0.0) or 0.0), 3),
        "elapsed_ms": int((time.time() - t0) * 1000),
    })
    return metrics


def _aggregate(rows: list[dict]) -> dict:
    """Başarılı satırlardan 4 boyutlu agregat."""
    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    n_err = len(rows) - n
    if n == 0:
        return {"n": 0, "n_error": n_err}
    return {
        "n": n,
        "n_error": n_err,
        "short_answer_rate": round(sum(r["has_short_answer"] for r in ok) / n, 4),
        "avg_turkish_purity": round(sum(r["turkish_purity"] for r in ok) / n, 4),
        "min_turkish_purity": round(min(r["turkish_purity"] for r in ok), 4),
        "avg_src_coverage": round(sum(r["src_coverage"] for r in ok) / n, 4),
        "length_in_target_rate": round(sum(r["length_in_target"] for r in ok) / n, 4),
        "avg_word_count": round(sum(r["word_count"] for r in ok) / n, 1),
        "truncation_rate": round(sum(r.get("is_truncated", False) for r in ok) / n, 4),
    }


def _print_summary(agg: dict, llm_mode: str, out_path: Path) -> None:
    print(f"\n{'=' * 64}")
    print(f"  DRAFT QUALITY — LLM={llm_mode}")
    print(f"{'=' * 64}")
    if not agg.get("n"):
        print(f"  başarılı koşum yok (n_error={agg.get('n_error', 0)})")
        print(f"  rapor: {out_path}")
        print(f"{'=' * 64}")
        return
    print(f"  vaka (başarılı)        : {agg['n']} (hata: {agg['n_error']})")
    print(f"  kısa-cevap oranı       : {agg['short_answer_rate']:.0%}")
    print(f"  ort. Türkçe saflığı    : {agg['avg_turkish_purity']:.1%} "
          f"(min: {agg['min_turkish_purity']:.1%})")
    print(f"  ort. kaynak bağı       : {agg['avg_src_coverage']:.0%}")
    print(f"  hedef-uzunluk oranı    : {agg['length_in_target_rate']:.0%} "
          f"({TARGET_WORD_MIN}-{TARGET_WORD_MAX} kelime)")
    print(f"  ort. kelime            : {agg['avg_word_count']}")
    print(f"  rapor: {out_path}")
    print(f"{'=' * 64}")
    if llm_mode == "mock":
        print("  [!] MockLLM canned cevap döndürür — metrikler ANLAMSIZ (smoke).")
        print("      Gerçek ölçüm: LLM_MODE=llamacpp uv run python -m eval.draft_quality")


async def main() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    llm_mode = os.environ.get("LLM_MODE", "mock")
    n = _eval_n()

    if llm_mode != "mock":
        _warm_retrieval_before_llm()

    from agents.graph import build_graph
    graph = build_graph()

    cases = _load_jsonl("answer_cases.jsonl")[:n]
    print(f"[*] {len(cases)} vaka × draft_quality | LLM={llm_mode}", flush=True)

    rows: list[dict] = []
    for i, case in enumerate(cases, 1):
        row = await _run_case(graph, case)
        if "error" in row:
            mark = f"ERROR: {row['error']}"
        else:
            mark = (f"sa={'Y' if row['has_short_answer'] else 'N'} "
                    f"pur={row['turkish_purity']:.0%} "
                    f"src={row['src_coverage']:.0%} wc={row['word_count']}")
        print(f"  [{i:2d}/{len(cases)}] {row['id']} {mark} "
              f"({row['elapsed_ms']}ms)", flush=True)
        rows.append(row)

    agg = _aggregate(rows)
    payload = {
        "git_sha": _git_sha(),
        "timestamp": datetime.now(UTC).isoformat(),
        "llm_mode": llm_mode,
        "n_requested": n,
        "target_word_range": [TARGET_WORD_MIN, TARGET_WORD_MAX],
        "note": "MockLLM ise metrikler canned çıktıdan gelir — tez sonucu değildir.",
        "summary": agg,
        "rows": rows,
    }
    out_path = RUNS_DIR / f"draft_quality_{payload['git_sha']}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_summary(agg, llm_mode, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
