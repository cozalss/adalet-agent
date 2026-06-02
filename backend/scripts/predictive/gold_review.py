"""Gold-aday ↔ hukukçu-dostu CSV köprüsü (Faz-5 insan-doğrulama adımı).

İki mod:
  export — data/predictive/gold_candidates.jsonl → gold_review.csv (Excel/Sheets'te
           açılır; hukukçu yalnız 'karar' sütununu doldurur) + TALIMAT.txt.
  ingest — hukukçunun doldurduğu gold_review.csv → data/predictive/gold_human.jsonl
           ({input_text, label}) → `eval_predict --gold` ile GERÇEK doğruluk ölçülür.

CSV utf-8-sig (BOM) ile yazılır → Excel Türkçe karakterleri doğru açar. doc_id ile
join (hukukçu satır sırasını değiştirse/silse bile sağlam). Saf parser test'li.

Kullanım:
  uv run python -m scripts.predictive.gold_review export
  # ... hukukçu gold_review.csv'yi doldurur, geri gönderir ...
  uv run python -m scripts.predictive.gold_review ingest
  uv run python -m predictive.eval_predict --gold data/predictive/gold_human.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_DIR = Path("data/predictive")
_CANDIDATES = _DIR / "gold_candidates.jsonl"
_CSV = _DIR / "gold_review.csv"
_HUMAN = _DIR / "gold_human.jsonl"
_TALIMAT = _DIR / "GOLD_REVIEW_TALIMAT.txt"
_VALID = {"kazandi", "kaybetti", "kismi", "belirsiz"}
_HEADERS = ["no", "doc_id", "dikkat", "olay_ozeti", "hukum",
            "ai_onerisi", "ai_gerekce", "karar", "not"]

_TALIMAT_METNI = """ADALET — Dava Sonucu Tahmini: İnsan Doğrulama Talimatı
=========================================================

Merhaba! Yapay zekâ modelimizin GERÇEK doğruluğunu ölçmek için senin hukuki
değerlendirmene ihtiyacımız var. gold_review.csv dosyasını Excel veya Google
Sheets ile aç ve şunu yap:

HER SATIR bir Yargıtay kararı. Senden istediğimiz: DAVACI (talebi öne süren
taraf) açısından kararın SONUCUNU, yalnız 'karar' sütununa yazman.

'karar' sütununa şu DÖRT kelimeden BİRİNİ yaz (küçük harf):
  kazandi   → davacının davası/talebi kabul edildi (veya aleyhine karar BOZULDU)
  kaybetti  → davacının davası/talebi reddedildi (veya ret kararı ONANDI)
  kismi     → kısmen kabul / kısmen ret
  belirsiz  → hükümden davacı açısından sonuç net çıkmıyor

Yardımcı sütunlar:
  - olay_ozeti / hukum : kararın metni (oku, sonucu buradan çıkar).
  - ai_onerisi         : modelin tahmini (BAŞLANGIÇ noktası — katılıyorsan aynısını
                         yaz, katılmıyorsan DOĞRUSUNU yaz, AI'yı düzeltmen değerli).
  - ai_gerekce         : AI'nın dayandığı cümle.
  - dikkat = 'İNCELE'  : iki AI yöntemimiz ÇELİŞTİ → bu satırlar en kritik, ekstra dikkat.

KURALLAR:
  1. Yalnız metinde YAZILI olanı değerlendir; dışarıdan bilgi katma.
  2. 'doc_id' ve 'no' sütunlarına DOKUNMA (eşleştirme için lazım).
  3. Emin değilsen 'belirsiz' yaz — uydurma tahmin yapma.
  4. İstersen 'not' sütununa kısa açıklama bırak.

Bitince dosyayı kaydet (CSV olarak) ve geri gönder. Teşekkürler!
"""


def export_csv(candidates: list[dict], csv_path: Path = _CSV) -> int:
    """Gold-adayları hukukçu-dostu CSV'ye yaz (karar sütunu boş). Satır sayısı döner."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADERS)
        for i, c in enumerate(candidates, 1):
            w.writerow([
                i, c.get("doc_id", ""),
                "İNCELE" if c.get("needs_review") else "",
                " ".join(str(c.get("input_text", "")).split())[:1500],
                " ".join(str(c.get("hukum_excerpt", "")).split())[:800],
                c.get("qwen_label", ""), c.get("quote", ""),
                "",  # karar — hukukçu doldurur
                "",  # not
            ])
    return len(candidates)


def normalize_label(value: str) -> str | None:
    """Hukukçunun yazdığını doğrula → geçerli etiket veya None (boş/geçersiz)."""
    v = (value or "").strip().lower()
    # Yaygın varyantları tolere et (büyük harf, noktalama, tr karakter zaten lower)
    v = v.replace("ı", "i").rstrip(".")
    return v if v in _VALID else None


def ingest_csv(candidates: list[dict], csv_path: Path = _CSV) -> tuple[list[dict], int]:
    """Doldurulmuş CSV → [{input_text, label}] (3-class; 'belirsiz' hariç) + atlanan sayısı.

    doc_id ile join — full input_text gold_candidates'tan alınır (CSV'deki kırpık değil).
    """
    by_doc = {c.get("doc_id", ""): c.get("input_text", "") for c in candidates}
    out: list[dict] = []
    skipped = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            label = normalize_label(row.get("karar", ""))
            doc = (row.get("doc_id", "") or "").strip()
            # 3-class eval'e yalnız geçerli + belirsiz-olmayan + eşleşen satırlar girer;
            # gerisi (boş/geçersiz/belirsiz) skipped sayılır.
            if label is not None and label != "belirsiz" and doc in by_doc:
                out.append({"input_text": by_doc[doc], "label": label})
            else:
                skipped += 1
    return out, skipped


def _load_candidates() -> list[dict]:
    if not _CANDIDATES.exists():
        raise SystemExit(f"{_CANDIDATES} yok — önce build_gold_eval çalıştır.")
    with _CANDIDATES.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Gold-aday ↔ hukukçu CSV köprüsü")
    parser.add_argument("mode", choices=["export", "ingest"])
    args = parser.parse_args()
    candidates = _load_candidates()

    if args.mode == "export":
        n = export_csv(candidates)
        _TALIMAT.write_text(_TALIMAT_METNI, encoding="utf-8")
        n_review = sum(1 for c in candidates if c.get("needs_review"))
        print(f"[+] {n} vaka -> {_CSV}")
        print(f"[+] talimat -> {_TALIMAT}")
        print(f"    ({n_review} satır 'İNCELE' işaretli — AI'lar çelişti)")
        print("    Bu 2 dosyayı hukukçuya gönder. Doldurunca: "
              "uv run python -m scripts.predictive.gold_review ingest")
    else:
        if not _CSV.exists():
            raise SystemExit(f"{_CSV} yok — hukukçunun doldurduğu CSV'yi buraya koy.")
        rows, skipped = ingest_csv(candidates)
        with _HUMAN.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[+] {len(rows)} insan-etiketli vaka -> {_HUMAN}  ({skipped} atlandı/boş/belirsiz)")
        print(f"    Ölç: uv run python -m predictive.eval_predict --gold {_HUMAN}")


if __name__ == "__main__":
    main()
