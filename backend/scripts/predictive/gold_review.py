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
_XLSX = _DIR / "gold_review.xlsx"
_HUMAN = _DIR / "gold_human.jsonl"
_TALIMAT = _DIR / "GOLD_REVIEW_TALIMAT.txt"
_VALID = {"kazandi", "kaybetti", "kismi", "belirsiz"}
_HEADERS = ["no", "doc_id", "dikkat", "olay_ozeti", "hukum",
            "ai_onerisi", "ai_gerekce", "karar", "not"]

_TALIMAT_METNI = """ADALET — Dava Sonucu Tahmini: İnsan Doğrulama Talimatı
=========================================================

Merhaba! Yapay zekâ modelimizin GERÇEK doğruluğunu ölçmek için senin hukuki
değerlendirmene ihtiyacımız var. gold_review.xlsx dosyasını Excel ile aç ve şunu yap:

HER SATIR bir Yargıtay kararı. Senden istediğimiz: DAVACI (talebi öne süren
taraf) açısından kararın SONUCUNU, yalnız 'KARAR (doldur)' (D) sütununda seçmen.

'KARAR (doldur)' (sarı sütun) hücresine tıkla → açılır menüden BİRİNİ seç:
  kazandi   → davacının davası/talebi kabul edildi (veya aleyhine karar BOZULDU)
  kaybetti  → davacının davası/talebi reddedildi (veya ret kararı ONANDI)
  kismi     → kısmen kabul / kısmen ret
  belirsiz  → hükümden davacı açısından sonuç net çıkmıyor

Yardımcı sütunlar:
  - HÜKÜM (oku)        : kararın sonuç bölümü — ASIL buradan karar ver.
  - olay_özeti (bağlam): davanın özeti (ek bağlam).
  - ai_önerisi         : modelin tahmini (BAŞLANGIÇ noktası — katılıyorsan aynısını
                         seç, katılmıyorsan DOĞRUSUNU seç; AI'yı düzeltmen çok değerli).
  - ai_gerekçe         : AI'nın dayandığı cümle.
  - dikkat = 'İNCELE'  : iki AI yöntemimiz ÇELİŞTİ (turuncu) → en kritik satırlar.

KURALLAR:
  1. Yalnız metinde YAZILI olanı değerlendir; dışarıdan bilgi katma.
  2. 'doc_id' ve 'no' sütunlarına DOKUNMA (eşleştirme için lazım).
  3. Emin değilsen 'belirsiz' seç — uydurma tahmin yapma.
  4. İstersen 'not' sütununa kısa açıklama bırak.

Bitince Excel'de KAYDET (.xlsx olarak kalsın) ve geri gönder. Teşekkürler!
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
                " ".join(str(c.get("input_text", "")).split())[:2500],
                " ".join(str(c.get("hukum_full") or c.get("hukum_excerpt", "")).split())[:4000],
                c.get("qwen_label", ""), c.get("quote", ""),
                "",  # karar — hukukçu doldurur
                "",  # not
            ])
    return len(candidates)


def _clean(text: object, n: int) -> str:
    """Boşlukları sadeleştir + kısalt (hücre okunabilir kalsın)."""
    return " ".join(str(text or "").split())[:n]


# .xlsx sütun düzeni — hukukçu soldan sağa: oku (hüküm) → seç (KARAR) → bağlam.
_XLSX_HEADERS = ["no", "dikkat", "HÜKÜM (oku)", "KARAR (doldur)", "ai_önerisi",
                 "ai_gerekçe", "olay_özeti (bağlam)", "not", "doc_id (dokunma)"]
_XLSX_WIDTHS = [5, 9, 85, 16, 12, 42, 62, 22, 16]


def export_xlsx(candidates: list[dict], xlsx_path: Path = _XLSX) -> int:
    """Gold-adayları hukukçu-dostu .xlsx'e yaz: geniş sarmalı hüküm + KARAR dropdown'u.

    openpyxl gerekir (uv pip install openpyxl). CSV'nin Excel-Türkçe ayraç + uzun-hücre
    sorununu çözer: tam biçimli, açılır-menülü, dondurulmuş başlık.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("openpyxl yok → `uv pip install openpyxl`") from exc

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "İnceleme"
    ws.append(_XLSX_HEADERS)
    hdr_fill = PatternFill("solid", fgColor="1F3A5F")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for i, c in enumerate(candidates, 1):
        ws.append([
            i, "İNCELE" if c.get("needs_review") else "",
            _clean(c.get("hukum_full") or c.get("hukum_excerpt"), 4000), "",  # TAM hüküm; KARAR boş
            c.get("qwen_label", ""), _clean(c.get("quote"), 500),
            _clean(c.get("input_text"), 2500), "", c.get("doc_id", ""),
        ])

    for idx, w in enumerate(_XLSX_WIDTHS):
        ws.column_dimensions[chr(65 + idx)].width = w
    wrap_top = Alignment(vertical="top", wrap_text=True)
    karar_fill = PatternFill("solid", fgColor="FFF2CC")   # sarı: doldur
    incele_fill = PatternFill("solid", fgColor="F8CBAD")  # turuncu: çelişki
    for r in range(2, len(candidates) + 2):
        for col in range(1, 10):
            ws.cell(r, col).alignment = wrap_top
        ws.row_dimensions[r].height = 120
        ws.cell(r, 4).fill = karar_fill
        if ws.cell(r, 2).value == "İNCELE":
            ws.cell(r, 2).fill = incele_fill

    dv = DataValidation(type="list", formula1='"kazandi,kaybetti,kismi,belirsiz"',
                        allow_blank=True)
    dv.promptTitle = "KARAR"
    dv.prompt = "Davacı açısından sonucu seç: kazandi / kaybetti / kismi / belirsiz"
    ws.add_data_validation(dv)
    dv.add(f"D2:D{len(candidates) + 1}")
    ws.freeze_panes = "A2"
    wb.save(xlsx_path)
    return len(candidates)


def ingest_xlsx(candidates: list[dict], xlsx_path: Path = _XLSX) -> tuple[list[dict], int]:
    """Doldurulmuş .xlsx → [{input_text, label}] + atlanan (doc_id ile join)."""
    from openpyxl import load_workbook

    by_doc = {c.get("doc_id", ""): c.get("input_text", "") for c in candidates}
    out: list[dict] = []
    skipped = 0
    ws = load_workbook(xlsx_path, read_only=True).active
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None or len(row) < 9:
            continue
        label = normalize_label(str(row[3] or ""))  # D = KARAR
        doc = str(row[8] or "").strip()             # I = doc_id
        if label is not None and label != "belirsiz" and doc in by_doc:
            out.append({"input_text": by_doc[doc], "label": label})
        else:
            skipped += 1
    return out, skipped


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
        # hukum_excerpt yalnız 400-char kesit → hukukçu yarım hüküm görür. Tam hükmü
        # parquet'ten çek (yoksa) + gold_candidates'a kalıcı yaz.
        if not all(c.get("hukum_full") for c in candidates):
            from scripts.predictive.build_gold_eval import enrich_candidates
            print("[*] tam hüküm parquet'ten çekiliyor...", flush=True)
            n_enr = enrich_candidates(candidates)
            with _CANDIDATES.open("w", encoding="utf-8") as f:
                for c in candidates:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
            print(f"[*] {n_enr}/{len(candidates)} adaya tam hüküm eklendi")
        n = export_xlsx(candidates)           # hukukçu-dostu Excel (asıl)
        export_csv(candidates)                # yedek (CSV)
        _TALIMAT.write_text(_TALIMAT_METNI, encoding="utf-8")
        n_review = sum(1 for c in candidates if c.get("needs_review"))
        print(f"[+] {n} vaka -> {_XLSX}  (Excel — hukukçuya BUNU gönder)")
        print(f"[+] yedek CSV -> {_CSV}")
        print(f"[+] talimat -> {_TALIMAT}")
        print(f"    ({n_review} satır 'İNCELE' işaretli — AI'lar çelişti)")
        print("    Doldurulunca: uv run python -m scripts.predictive.gold_review ingest")
    else:
        # xlsx tercih; yoksa csv (hukukçu hangi formatı döndürdüyse).
        if _XLSX.exists():
            rows, skipped = ingest_xlsx(candidates)
        elif _CSV.exists():
            rows, skipped = ingest_csv(candidates)
        else:
            raise SystemExit(f"{_XLSX} / {_CSV} yok — hukukçunun doldurduğu dosyayı buraya koy.")
        with _HUMAN.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[+] {len(rows)} insan-etiketli vaka -> {_HUMAN}  ({skipped} atlandı/boş/belirsiz)")
        print(f"    Ölç: uv run python -m predictive.eval_predict --gold {_HUMAN} --gold-kind human")


if __name__ == "__main__":
    main()
