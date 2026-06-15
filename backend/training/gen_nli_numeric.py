"""Sayısal-çıkarım NLI çifti üretici — TR-legal NLI fine-tune verisi (anti-halüsinasyon FAZ 3.1).

KÖK SORUN: mDeBERTa XNLI Türkçe sayısal/eşik çıkarımını NEUTRAL sayıyor ("en az 5 yıl" vs
"en az 1 yıl" → contradiction DEĞİL); çelişki recall ~%50. Bu üretici, eşik-temelli
çıkarımları premise/hypothesis çiftine çevirir ve ETİKETİ DETERMİNİSTİK sayısal
karşılaştırmadan üretir (gün-normalize: yıl=365, ay=30, hafta=7, gün=1) → insan-etiket gerekmez.

Üretilen sınıflar (premise = "X için en az N birim gerekir"):
  - ENTAILMENT:    "M birim (M ≥ N) → hak kazanır"  +  doğru-eşik paraphrase
  - CONTRADICTION: "M birim (M < N) → hak kazanır" (eşik-altı POZİTİF, NLI'nın kaçırdığı sınıf)
                   + "en az P birim gerekir" (P ≠ N, yanlış eşik) + "M < N → kazanamaz" yanlış-negatif
  - NEUTRAL:       aynı konu ama eşik-ilgisiz cümle (hesaplama/usul)

Çıktı nli_tr_gold formatı (id/premise/hypothesis/label) → lora_nli.py train + nli_tr_eval gold.

Çalıştır:
    uv run python -m training.gen_nli_numeric --out data/eval_benchmark/nli_numeric_train.jsonl --n 4000
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

_UNIT_DAYS = {"yıl": 365, "ay": 30, "hafta": 7, "gün": 1}
_NUM_WORD = {1: "bir", 2: "iki", 3: "üç", 4: "dört", 5: "beş", 6: "altı",
             7: "yedi", 8: "sekiz", 9: "dokuz", 10: "on", 14: "on dört",
             15: "on beş", 30: "otuz", 60: "altmış", 90: "doksan"}


def _say(n: int, *, yazi: bool) -> str:
    return _NUM_WORD.get(n, str(n)) if yazi else str(n)


def _days(n: int, unit: str) -> int:
    return n * _UNIT_DAYS[unit]


# Eşik-temelli hukuki senaryolar: (konu, eşik_sayı, eşik_birim, hak_fiili, gereklilik_cümlesi)
_SCENARIOS = [
    ("kıdem tazminatı", 1, "yıl", "kıdem tazminatına hak kazanır",
     "Kıdem tazminatı için işçinin en az {N} {U} çalışmış olması gerekir."),
    ("yıllık izin", 1, "yıl", "yıllık ücretli izne hak kazanır",
     "Yıllık ücretli izne hak kazanmak için en az {N} {U} çalışma şartı aranır."),
    ("cayma hakkı", 14, "gün", "cayma hakkını kullanabilir",
     "Mesafeli sözleşmede tüketici, malı teslim aldığı tarihten itibaren {N} {U} içinde cayabilir."),
    ("iptal davası", 60, "gün", "iptal davası açabilir",
     "İdari işleme karşı iptal davası, tebliğden itibaren {N} {U} içinde açılır."),
    ("vergi davası", 30, "gün", "vergi mahkemesinde dava açabilir",
     "Vergi/ceza ihbarnamesine karşı dava açma süresi {N} {U}dır."),
    ("icra itirazı", 7, "gün", "ödeme emrine itiraz edebilir",
     "Ödeme emrine itiraz, tebliğden itibaren {N} {U} içinde yapılır."),
]

# Eşik-ilgisiz (neutral) paraphrase'ler — aynı konu, sayısal-eşik İÇERMEZ.
_NEUTRAL_TAILS = {
    "kıdem tazminatı": "Kıdem tazminatı son brüt ücret üzerinden hesaplanır.",
    "yıllık izin": "Yıllık izin süresi kıdeme göre artar.",
    "cayma hakkı": "Cayma bildirimi yazılı veya kalıcı veri saklayıcısıyla yapılır.",
    "iptal davası": "İptal davası idari işlemin hukuka aykırılığı iddiasıyla açılır.",
    "vergi davası": "Vergi davası vergi mahkemesinde görülür.",
    "icra itirazı": "İtiraz takibi durdurur, alacaklı itirazın iptalini ister.",
}


def _gen_for_scenario(konu, n, unit, fiil, prem_tpl, *, yazi: bool) -> list[dict]:
    """Bir senaryo + yazı/rakam stili için tüm sınıfları üret."""
    premise = prem_tpl.format(N=_say(n, yazi=yazi), U=unit)
    min_days = _days(n, unit)
    rows: list[dict] = []

    def add(hyp: str, label: str) -> None:
        rows.append({"premise": premise, "hypothesis": hyp, "label": label})

    # ENTAILMENT: eşik-üstü/eşit süre → hak doğar (doğru çıkarım)
    for m, mu in [(n, unit), (n + 1, unit), (n * 2, unit)]:
        add(f"{_say(m, yazi=yazi).capitalize()} {mu} olan kişi {fiil}.", "entailment")
    # ENTAILMENT: doğru-eşik paraphrase
    add(f"{konu.capitalize()} için en az {_say(n, yazi=yazi)} {unit} şartı vardır.", "entailment")

    # CONTRADICTION: eşik-ALTI süre → "hak kazanır" (NLI'nın kaçırdığı POZİTİF fabrike)
    sub = []
    if unit == "yıl":
        sub = [(6, "ay"), (3, "ay"), (n * 365 // 2, "gün")]
    elif unit == "gün" and n >= 7:
        sub = [(max(1, n - 3), "gün"), (n // 2, "gün")]
    elif unit == "ay":
        sub = [(max(1, n - 1), "ay"), (10, "gün")]
    for m, mu in sub:
        if _days(m, mu) < min_days:
            add(f"{_say(m, yazi=yazi).capitalize()} {mu} olan kişi {fiil}.", "contradiction")
    # CONTRADICTION: yanlış eşik (P ≠ N)
    for p in (n + 2, n * 3) if unit != "gün" else (n + 7, n * 2):
        if p != n:
            add(f"{konu.capitalize()} için en az {_say(p, yazi=yazi)} {unit} gerekir.", "contradiction")

    # NEUTRAL: aynı konu, eşik-ilgisiz
    add(_NEUTRAL_TAILS[konu], "neutral")
    return rows


def generate(limit: int) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for yazi in (False, True):
        for konu, n, unit, fiil, tpl in _SCENARIOS:
            for r in _gen_for_scenario(konu, n, unit, fiil, tpl, yazi=yazi):
                key = (r["premise"], r["hypothesis"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(r)
    # Determinik tekrarla hedef boyuta ulaş (epoch yerine örnek-çoğaltma değil — çeşitlilik
    # şablon sayısıyla sınırlı; limit yalnız tavan). Benzersiz set döndür, limit uygula.
    return rows[:limit] if limit else rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=0, help="tavan (0=tüm benzersiz)")
    args = ap.parse_args()
    rows = generate(args.n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    from collections import Counter
    dist = Counter(r["label"] for r in rows)
    with args.out.open("w", encoding="utf-8") as fh:
        for i, r in enumerate(rows):
            fh.write(json.dumps({"id": f"num{i:04d}", **r}, ensure_ascii=False) + "\n")
    print(f"[OK] {len(rows)} benzersiz çift → {args.out}")
    print(f"     dağılım: {dict(dist)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
