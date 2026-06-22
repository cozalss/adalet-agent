"""docx → PDF (Word COM) → PNG (PyMuPDF). Görsel doğrulama için önizleme üretir."""
import sys
from pathlib import Path

import fitz  # PyMuPDF
import win32com.client

HERE = Path(__file__).resolve().parent


def render(docx_name: str, out_dir: str = "preview", dpi: int = 110, max_pages: int = 6):
    docx_path = HERE / docx_name
    pdf_path = HERE / (docx_path.stem + ".pdf")
    out = HERE / out_dir
    out.mkdir(exist_ok=True)

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(docx_path))
        doc.SaveAs(str(pdf_path), FileFormat=17)  # 17 = wdFormatPDF
        doc.Close(False)
    finally:
        word.Quit()

    pdf = fitz.open(str(pdf_path))
    n = min(max_pages, pdf.page_count)
    paths = []
    for i in range(n):
        pix = pdf[i].get_pixmap(dpi=dpi)
        p = out / f"p{i + 1:02d}.png"
        pix.save(str(p))
        paths.append(p)
    print(f"pages={pdf.page_count} rendered={n} -> {out}")
    pdf.close()
    return paths


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "2209-A_Turkce_Hukuk_RAG_Basvuru_Taslagi.docx"
    render(name)
