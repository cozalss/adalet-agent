from pathlib import Path
from zipfile import ZipFile
from io import BytesIO

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "docs" / "tubitak" / "2209-A_arastirma_onerisi_formu_09102025.docx"
OUT = ROOT / "docs" / "tubitak" / "2209-A_Turkce_Hukuk_RAG_Basvuru_Taslagi_unscrubbed.docx"

FONT = "Arial"
SIZE = Pt(9)
FULL_WIDTH_TWIPS = 9360


def norm_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def apply_run_font(run, bold=None):
    run.font.name = FONT
    run.font.size = SIZE
    if bold is not None:
        run.bold = bold


def apply_paragraph_format(paragraph):
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    for run in paragraph.runs:
        apply_run_font(run)


def set_cell_text(cell, text: str, bold_first_line: bool = False):
    cell.text = ""
    lines = norm_text(text).split("\n")
    if not lines:
        return
    p = cell.paragraphs[0]
    for idx, line in enumerate(lines):
        if idx:
            p = cell.add_paragraph()
        run = p.add_run(line)
        apply_run_font(run, bold=(bold_first_line and idx == 0))
        apply_paragraph_format(p)


def set_table_width(table, widths_twips):
    table.autofit = False
    table.allow_autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(sum(widths_twips)))

    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            width = widths_twips[min(idx, len(widths_twips) - 1)]
            cell.width = Inches(width / 1440)
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:type"), "dxa")
            tc_w.set(qn("w:w"), str(width))


def set_paragraph_text(paragraph, text: str, bold: bool = False):
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    run = paragraph.add_run(text)
    apply_run_font(run, bold=bold)
    apply_paragraph_format(paragraph)


def insert_paragraph_after(paragraph, text: str = "", bold: bool = False) -> Paragraph:
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    new_para = Paragraph(new_p, paragraph._parent)
    if text:
        run = new_para.add_run(text)
        apply_run_font(run, bold=bold)
    apply_paragraph_format(new_para)
    return new_para


def shade_cell(cell, fill: str = "EAF0F8"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, margin_twips: int = 90):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for side in ("top", "left", "bottom", "right"):
        node = tc_mar.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(margin_twips))
        node.set(qn("w:type"), "dxa")


def style_all_tables(doc: Document):
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                set_cell_margins(cell)
                for p in cell.paragraphs:
                    apply_paragraph_format(p)


def configure_document(doc: Document):
    section = doc.sections[0]
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = SIZE
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    for style_name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = FONT
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)


def add_para(parent, text: str = "", bold: bool = False, size: float = 9, align=None):
    p = parent.add_paragraph()
    if text:
        r = p.add_run(text)
        r.font.name = FONT
        r.font.size = Pt(size)
        r.bold = bold
    apply_paragraph_format(p)
    if align is not None:
        p.alignment = align
    return p


def add_section(doc: Document, title: str, level: int = 1):
    p = doc.add_paragraph()
    r = p.add_run(title)
    r.font.name = FONT
    r.font.size = Pt(11 if level == 1 else 10)
    r.bold = True
    r.font.color.rgb = RGBColor(31, 54, 82)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(5)
    return p


def add_box(doc: Document, title: str, body: str):
    table = doc.add_table(rows=2, cols=1)
    table.style = "Table Grid"
    set_table_width(table, [FULL_WIDTH_TWIPS])
    set_cell_text(table.cell(0, 0), title, bold_first_line=True)
    shade_cell(table.cell(0, 0), "DDEAF7")
    set_cell_text(table.cell(1, 0), body)
    style_all_tables(doc)
    add_para(doc, "")
    return table


def add_key_value_table(doc: Document, rows):
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    set_table_width(table, [2600, FULL_WIDTH_TWIPS - 2600])
    for idx, (key, value) in enumerate(rows):
        set_cell_text(table.cell(idx, 0), key, bold_first_line=True)
        shade_cell(table.cell(idx, 0), "EEF3F8")
        set_cell_text(table.cell(idx, 1), value)
    style_all_tables(doc)
    add_para(doc, "")
    return table


def add_data_table(doc: Document, headers, rows, widths):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    set_table_width(table, widths)
    for idx, header in enumerate(headers):
        set_cell_text(table.cell(0, idx), header, bold_first_line=True)
        shade_cell(table.cell(0, idx), "DDEAF7")
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, value in enumerate(row):
            set_cell_text(table.cell(r_idx, c_idx), value)
    style_all_tables(doc)
    add_para(doc, "")
    return table


def add_references(doc: Document):
    add_section(doc, "6. EKLER", level=1)
    add_section(doc, "EK-1: KAYNAKLAR", level=2)
    for ref in REFERENCES:
        p = doc.add_paragraph(style=None)
        r = p.add_run(ref)
        r.font.name = FONT
        r.font.size = Pt(8)
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.first_line_indent = Cm(-0.4)
        p.paragraph_format.space_after = Pt(3)


def add_kv_para(doc: Document, key: str, value: str):
    p = doc.add_paragraph()
    r = p.add_run(f"{key}: ")
    r.font.name = FONT
    r.font.size = SIZE
    r.bold = True
    v = p.add_run(value)
    v.font.name = FONT
    v.font.size = SIZE
    apply_paragraph_format(p)
    return p


def add_block(doc: Document, title: str, body: str):
    add_para(doc, title, bold=True, size=9)
    for para in [part.strip() for part in norm_text(body).split("\n\n") if part.strip()]:
        add_para(doc, para, size=9)


def add_compact_item(doc: Document, number: int, title: str, lines):
    add_para(doc, f"{number}. {title}", bold=True, size=9)
    for label, value in lines:
        add_kv_para(doc, label, value)


SUMMARY = """
Bu proje, Türkçe hukuk soru-cevap sistemlerinde büyük dil modellerinin ürettiği desteklenmemiş veya uydurma iddiaları azaltmak için kaynak temelli RAG (Retrieval-Augmented Generation) ve iddia doğrulama katmanlarının etkisini ölçmeyi amaçlamaktadır. Çalışma; tüketici, iş hukuku, kira, icra, trafik, vergi, tapu ve idari uyuşmazlıklar gibi medeni/idari hukuk alanlarında, kamuya açık mevzuat ve yargı kararları üzerinde yürütülecektir.

Araştırmanın temel sorusu şudur: Türkçe hukuk bağlamında, cevap üretiminden sonra her hukuki iddianın kaynak parçalarıyla ayrı ayrı doğrulanması, klasik RAG yaklaşımına göre halüsinasyon ve hatalı kesinlik oranını anlamlı biçimde düşürür mü? Bu soru deneysel olarak; doğrulama kapalı/açık, farklı arama stratejileri ve farklı LLM sağlayıcıları karşılaştırılarak incelenecektir. OpenAI API, yürütülebilir ve kararlı ana model sağlayıcısı olarak kullanılacak; yerel Qwen kurulumu ise donanım/sürücü riskleri nedeniyle zorunlu başarı koşulu değil, imkan oluşursa ek karşılaştırma kolu olarak ele alınacaktır.

Ön çalışma kapsamında FastAPI tabanlı bir araştırma prototipi, hibrit arama altyapısı, kaynak gösterimli cevap üretimi, çok katmanlı risk koruması ve React arayüzü hazırlanmıştır. Mevcut ölçümlerde 159.362 vektörlük hukuk külliyatı, 186 vakalık retrieval değerlendirmesi, 104 halüsinasyon test vakasında yüzde 100 yakalama ve 46 uydurma eşik vakasında F1=0,9767 sonucu elde edilmiştir. Proje süresince bu ön çalışma, insan etiketli altın veri seti, RAGAS benzeri otomatik ölçümler, hata analizi ve tekrarlanabilir deney raporuyla akademik araştırma çıktısına dönüştürülecektir.

Beklenen çıktı; hukuki tavsiye vermeyen, kaynak şeffaflığını öne çıkaran, riskli cevapları reddedebilen ve Türkçe hukuk yapay zekası çalışmalarında kullanılabilecek ölçülebilir bir yöntem önerisidir.
"""

SCIENTIFIC_QUALITY = """
Hukuk alanında büyük dil modellerinin kullanımı, vatandaşların hak arama süreçleri ve bilgiye erişimi açısından önemli fırsatlar sunarken, hatalı veya kaynaksız cevap üretme riski nedeniyle yüksek toplumsal sorumluluk gerektirir. Özellikle Türkçe hukuk metinlerinde mevzuat, içtihat ve idari görüşlerin dili; genel amaçlı modellerin eğitim dağılımından farklıdır. Bu durum, modelin doğru görünen ancak kaynağı bulunmayan hukuki iddialar üretmesine, uygulanmayan süre veya parasal eşikler uydurmasına ve kullanıcının yanlış yönlendirilmesine yol açabilir.

Literatürde RAG yaklaşımı, dil modelinin cevabını dış bilgi kaynaklarıyla destekleyerek güncellik ve izlenebilirlik sorunlarını azaltmayı hedefler. Ancak yalnızca ilgili belge getirmek, cevaptaki her cümlenin gerçekten o kaynak tarafından desteklendiğini garanti etmez. Hukuk gibi riskli alanlarda araştırma problemi bu nedenle "belge bulundu mu?" sorusundan "cevaptaki her hukuki iddia kanıtla destekleniyor mu?" sorusuna taşınmalıdır. Bu proje, Türkçe hukuk soru-cevaplarında iddia düzeyi doğrulamanın halüsinasyon azaltımına etkisini deneysel olarak ölçerek bu boşluğa odaklanır.

Araştırma önerisinin bilimsel niteliği üç noktada yoğunlaşmaktadır. Birincisi, Türkçe ve hukuk alanına özgü değerlendirme senaryoları oluşturulacaktır. İkincisi, klasik RAG hattı ile iddia doğrulama katmanlı RAG hattı aynı soru setleri üzerinde karşılaştırılacaktır. Üçüncüsü, sistem sadece nihai cevap kalitesine göre değil; kaynak kapsama, iddia desteği, uydurma eşik yakalama, yanlış ret oranı, gecikme ve maliyet gibi çok boyutlu ölçütlerle değerlendirilecektir.

Ön çalışmada sekiz hukuk alanını kapsayan bir prototip geliştirilmiş, 159.362 vektörlük kamu hukuku külliyatı indekslenmiş, hibrit arama ve tekrar sıralama bileşenleri denenmiştir. 186 vakalık retrieval ölçümünde domain@5 yüzde 97,3 ve MRR 0,879; 104 halüsinasyon vakalık risk koruması testinde tam yakalama; uydurma eşik testinde F1=0,9767 elde edilmiştir. Bu sonuçlar, önerilen araştırmanın uygulanabilir olduğunu göstermekte; ancak TÜBİTAK projesinin asıl katkısı, bu ön çalışmayı kontrollü deney, insan etiketli veri ve akademik raporlama düzeyine yükseltmektir.

Proje, TÜBİTAK öncelikli alanlarıyla da uyumludur: yapay zeka, bilişim hukuku, büyük veri/bulut bilişim ve siber güvenlik başlıklarıyla doğrudan ilişkilidir. Çalışma bir ticari ürün veya marka tanıtımı olarak değil, Türkçe hukuk yapay zekası için ölçülebilir, kaynak şeffaflığı yüksek ve sorumlu üretken yapay zeka yönteminin araştırılması olarak tasarlanmıştır.
"""

OBJECTIVES = """
Projenin genel amacı, Türkçe hukuk soru-cevap sistemlerinde kaynak temelli RAG ve iddia doğrulama katmanlarının halüsinasyon azaltımına etkisini deneysel olarak ölçmek ve tekrarlanabilir bir değerlendirme çerçevesi ortaya koymaktır.

Özel hedefler:
1. Tüketici, iş hukuku, kira, icra, trafik, vergi, tapu ve idari hukuk alanlarından oluşan, kamu kaynaklarına dayalı en az 150-300 soruluk değerlendirme seti hazırlamak; soruları "cevaplanabilir", "eksik kaynaklı", "alan dışı" ve "uydurma eşik riski" gibi kategorilere ayırmak.
2. Klasik RAG hattı ile iddia doğrulama katmanlı RAG hattını aynı veri üzerinde karşılaştırmak.
3. Cevaplardaki hukuki iddiaları kaynak parçası düzeyinde kontrol ederek destekli, desteksiz ve çelişkili iddia oranlarını ölçmek.
4. Halüsinasyon yakalama, yanlış ret, kaynak doğruluğu, cevaplanabilirlik, gecikme ve maliyet ölçütlerini birlikte raporlamak.
5. OpenAI API tabanlı kararlı çalışma hattını ana deney ortamı yapmak; yerel Qwen kurulumunu sadece kaynak ve zaman yeterliyse ek karşılaştırma olarak kullanmak.
6. Araştırma sonunda yöntem, veri şeması, deney sonuçları, hata analizi ve etik kullanım ilkelerini içeren bir teknik rapor ve sunum hazırlamak.

Başarı ölçütleri; halüsinasyonlu cevaplarda en az yüzde 80 yakalama, temiz ve cevaplanabilir sorularda yanlış ret oranının yüzde 10 altında tutulması, kaynak gösterimli cevaplarda iddia-destek oranının doğrulama kapalı hatta göre en az 30 puan iyileşmesi ve deneylerin yeniden üretilebilir komutlarla raporlanmasıdır.
"""

METHOD = """
Araştırma yöntemi kontrollü karşılaştırmalı deney tasarımına dayanır. Bağımsız değişkenler; arama stratejisi (hibrit arama, tekrar sıralama, isteğe bağlı HyDE/multi-query), LLM sağlayıcısı (OpenAI ana hat, yerel Qwen opsiyonel hat) ve doğrulama durumu (doğrulama kapalı/açık, katman seviyesi) olarak belirlenecektir. Bağımlı değişkenler; halüsinasyon yakalama, yanlış ret, kaynak doğruluğu, iddia desteği, cevap kalitesi, gecikme ve maliyettir.

Veri hazırlama aşamasında kamuya açık mevzuat, yargı kararları ve idari görüşler kullanılacaktır. Kullanıcı verisi veya özel kişisel veri proje veri setine dahil edilmeyecektir. Gerçekçi sorular, anonimleştirilmiş veya sentetik biçimde hazırlanacak; gerekirse etik kurul muafiyeti/onayı alınacaktır. Her soru için beklenen hukuk alanı, kaynak türü, cevaplanabilirlik durumu ve risk etiketi kaydedilecektir. İnsan değerlendirmesi yapılacak alt kümede en az iki değerlendiriciyle tutarlılık kontrolü hedeflenecek, uyuşmazlıklar açıklama kılavuzuna göre giderilecektir.

Deney hattı şu adımlardan oluşur: kullanıcının sorusu alınır; alan sınıflandırması ve güvenlik kontrolü yapılır; ilgili hukuk kaynakları hibrit arama ile getirilir; model kaynaklara dayanarak taslak cevap üretir; cevap hukuki iddialara ayrılır; her iddia getirilen kaynak parçalarıyla doğrulanır; desteklenmeyen, çelişkili veya uydurma görünen iddialar işaretlenir; nihai cevap kaynaklı, sınırlı ve hukuki danışmanlık vermeyen formatta üretilir. Riskli durumlarda sistem cevap vermek yerine ek bilgi ister veya güvenli ret üretir.

Analiz aşamasında doğrulama kapalı ve doğrulama açık koşullar aynı soru setinde karşılaştırılacaktır. Sayısal sonuçlar Wilson güven aralıkları, eşleşmiş karşılaştırmalar ve hata türlerine göre ayrıştırılmış tablolarla raporlanacaktır. Otomatik ölçümlerin yanı sıra insan değerlendirmesiyle kaynak uygunluğu, cevap faydası ve riskli kesinlik kontrol edilecektir. Bu sayede yalnızca "sistem çalışıyor" değil, hangi bileşenin hangi hata türünü azalttığı gösterilecektir.

Ön çalışma altyapısı bu yöntemi uygulamaya hazırdır: FastAPI tabanlı backend, LangGraph tarzı çok adımlı ajan akışı, Qdrant vektör indeksi, BGE-M3/Mürşit tabanlı arama denemeleri, Supabase kimlik/veri yönetimi, React arayüzü ve otomatik test kapıları bulunmaktadır. Mevcut doğrulama komutlarında üretime hazırlık, dokümantasyon tutarlılığı, canlı entegrasyon sözleşmeleri ve risk koruması kontrolleri başarılı çalışmıştır.
"""

OTHER_TOPICS = """
Bu başvuru bir ürün veya marka tanıtımı değildir. Mevcut kod tabanı yalnızca araştırmanın uygulanabilirliğini gösteren ön çalışma ve deney platformu olarak kullanılacaktır. Başlık, özet ve yöntem ticari ad yerine bilimsel probleme odaklanacak şekilde hazırlanmıştır.

Üretken yapay zeka kullanımı sorumlu biçimde yönetilecektir. Model çıktıları tek başına hukuki tavsiye olarak sunulmayacak, kaynakla desteklenmeyen iddialar reddedilecek ve proje çıktılarında yapay zeka kullanımının sınırları açıkça belirtilecektir. OpenAI API ana deney hattı olarak seçilmiştir; çünkü yerel Qwen dağıtımı GPU, CUDA/sürücü uyumluluğu, bellek ve performans açısından proje takvimi için risk taşır. Yerel model karşılaştırması, başarı için zorunlu değil opsiyonel araştırma genişletmesi olarak planlanmıştır.

Bütçe, 2209-A üst limitine uygun biçimde çoğunlukla hizmet alımı/API kredisi, bulut test ortamı ve sarf niteliğindeki araştırma giderlerine ayrılacaktır. Kongre katılımı, yayın ücreti, konaklama, yolluk ve gündelik gibi program dışı kalemler bütçeye konulmayacaktır.
"""

WORK_ROWS = [
    ("Ay 1", "Kapsam kesinleştirme, etik/muafiyet kontrolü, veri ve soru şeması hazırlığı", "Proje yürütücüsü, danışman", "Etik durum netleşir; 8 alan için soru ve etiket şeması hazırlanır. Katkı: %15"),
    ("Ay 2-3", "Kamu kaynaklarının temizlenmesi, indeks güncellemesi, altın/değerlendirme seti oluşturma", "Proje yürütücüsü", "En az 150-300 vakalık değerlendirme seti ve kaynak eşlemeleri hazırlanır. Katkı: %20"),
    ("Ay 4-5", "Baseline RAG ve doğrulama katmanlı RAG deneylerinin çalıştırılması", "Proje yürütücüsü", "Aynı soru setinde doğrulama açık/kapalı sonuçları üretilir. Katkı: %20"),
    ("Ay 6-7", "İnsan değerlendirmesi, hata analizi, yanlış ret ve uydurma eşik incelemesi", "Proje yürütücüsü, danışman", "Hata türleri ve insan değerlendirme tabloları tamamlanır. Katkı: %15"),
    ("Ay 8-9", "OpenAI ana hat sonuçlarının maliyet/gecikme analizi; imkan varsa Qwen opsiyonel karşılaştırması", "Proje yürütücüsü", "Kararlı ana sonuçlar raporlanır; Qwen sonucu varsa ek deney olarak sunulur. Katkı: %10"),
    ("Ay 10-12", "Teknik rapor, akademik poster/sunum, tekrar üretilebilir deney dosyaları ve sonuçların yayıma hazırlanması", "Proje yürütücüsü, danışman", "Nihai rapor, sunum ve ekler teslim edilir. Katkı: %20"),
]

RISK_ROWS = [
    ("Yerel Qwen dağıtımının GPU/CUDA/bellek uyumsuzluğu nedeniyle gecikmesi", "Orta", "OpenAI API ana hat olarak kullanılacak; Qwen sadece opsiyonel karşılaştırma olacaktır. Model sağlayıcı adaptörü aynı tutulacaktır.", "Deneylerin ana sonucu OpenAI hattından alınarak takvim korunur."),
    ("API maliyeti veya hız sınırı nedeniyle deneylerin aksaması", "Orta", "Soru sayısı kademeli artırılacak, önbellekleme ve örnekleme uygulanacak, bütçe üst limiti tanımlanacaktır.", "Minimum veri setiyle temel hipotez test edilir; genişletme bütçeye göre yapılır."),
    ("Hukuki halüsinasyon veya hatalı kesinlik üretimi", "Yüksek", "Kaynak zorunluluğu, iddia doğrulama, güvenli ret ve kullanıcıya hukuki danışmanlık yapılmadığı uyarısı kullanılacaktır.", "Riskli cevaplar reddedilir veya ek bilgi istenir."),
    ("İnsan etiketlemede tutarsızlık", "Orta", "Etiketleme kılavuzu hazırlanacak; örnek vakalarla kalibrasyon yapılacak; mümkünse değerlendiriciler arası uyum ölçülecektir.", "Uyuşmazlıklar danışman kontrolünde karara bağlanır."),
    ("Kişisel veri veya etik onay riski", "Düşük/Orta", "Yalnızca kamuya açık hukuk kaynakları ve anonim/sentetik sorular kullanılacak; gerekirse etik kurul muafiyeti/onayı alınacaktır.", "Gerçek kullanıcı verisi deney setine dahil edilmez."),
]

FACILITY_ROWS = [
    ("Mevcut araştırma prototipi ve kod tabanı", "FastAPI backend, React arayüz, Supabase kimlik/veri yönetimi, Qdrant vektör indeksi, otomatik test ve ölçüm komutları hazırdır.", "Veri işleme, deney yürütme ve sonuç toplama için kullanılacaktır."),
    ("Kamuya açık hukuk kaynakları", "Mevzuat, yargı kararları ve idari görüşlerden oluşan ön indeks; 159.362 vektörlük mevcut çalışma kopyası bulunmaktadır.", "Retrieval ve kaynak doğrulama deneylerinin temel veri tabanını oluşturacaktır."),
    ("Model ve hesaplama olanakları", "OpenAI API ana yürütme hattı; yerel GPU/CPU ortamı ve Qwen kurulumu opsiyonel karşılaştırma için değerlendirilecektir.", "Kararlı deney üretimi ve sınırlı maliyetli model karşılaştırması sağlar."),
    ("Üniversite danışmanlığı ve çalışma ortamı", "Danışman akademik denetimi, etik uygunluk kontrolü ve raporlama geri bildirimi sağlayacaktır.", "Araştırma tasarımı, değerlendirme ve sonuçların akademik niteliğini güçlendirir."),
]

IMPACT = """
Bilimsel çıktı: Türkçe hukuk RAG sistemleri için kaynak temelli halüsinasyon değerlendirme yöntemi, etiketli/yarı etiketli soru seti, karşılaştırmalı deney raporu ve hata taksonomisi üretilecektir.

Toplumsal çıktı: Vatandaşların hukuki bilgi ararken kaynak görebildiği, kesin danışmanlık iddiası taşımayan ve riskli cevapları reddedebilen sorumlu bir yapay zeka yaklaşımı örneklenecektir.

Yaygınlaştırma: Proje sonunda teknik rapor, poster/sunum, mümkünse açık kaynak deney betikleri ve üniversite içi/öğrenci etkinliklerinde paylaşılabilecek kısa demo hazırlanacaktır.

Sonraki çalışmalar: İnsan etiketli veri setinin genişletilmesi, farklı hukuk alanlarına yayılım, 1002-A/2209-B başvuruları, bitirme tezi ve akademik yayın hazırlığı için temel oluşturacaktır.
"""

REFERENCES = [
    "Lewis, P. vd. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. arXiv:2005.11401. https://arxiv.org/abs/2005.11401",
    "Gao, L. vd. (2022). Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE). arXiv:2212.10496. https://arxiv.org/abs/2212.10496",
    "Chen, J. vd. (2024). BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings. arXiv:2402.03216. https://arxiv.org/abs/2402.03216",
    "Dahl, M. vd. (2024). Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models. arXiv:2401.01301. https://arxiv.org/abs/2401.01301",
    "TÜBİTAK. 2209-A Üniversite Öğrencileri Araştırma Projeleri Destekleme Programı. https://tubitak.gov.tr/tr/burslar/lisans-onlisans/destek-programlari/2209-universite-ogrencileri-arastirma-projeleri-destekleme-programi",
    "TÜBİTAK. 2209-A 2025 Yılı Çağrı Duyurusu ve Araştırma Önerisi Formu. https://tubitak.gov.tr/tr/duyuru/2209-universite-ogrencileri-arastirma-projeleri-destekleme-programi-2025-yili-cagrisi-acildi",
    "TÜBİTAK. Öncelikli Alanlar Listesi 2025. https://tubitak.gov.tr/sites/default/files/2025-07/Oncelikli_Alanlar_2025-2.pdf",
]


def main():
    doc = Document()
    configure_document(doc)

    # Cover page: use the official template logo when available, but build the
    # layout ourselves to avoid the source template's renderer-specific table bug.
    if TEMPLATE.exists():
        try:
            with ZipFile(TEMPLATE) as zf:
                logo = BytesIO(zf.read("word/media/image1.jpeg"))
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(logo, width=Inches(1.05))
        except KeyError:
            pass

    title_lines = [
        "TÜBİTAK 2209-A ÜNİVERSİTE ÖĞRENCİLERİ ARAŞTIRMA PROJELERİ DESTEKLEME PROGRAMI",
        "ARAŞTIRMA ÖNERİSİ FORMU",
    ]
    for line in title_lines:
        p = add_para(doc, line, bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
        p.paragraph_format.space_after = Pt(4)

    add_para(
        doc,
        "Başvuru formunun Arial 9 yazı tipinde, ekler hariç toplam 20 sayfayı geçmeyecek şekilde hazırlanması hedeflenmiştir.",
        bold=True,
        size=9,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    add_para(doc, "2026 Yılı", bold=True, size=11, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "[Çağrı dönemine göre güncellenecek] Dönem Başvurusu", bold=True, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_page_break()

    add_para(
        doc,
        "2209-A ÜNİVERSİTE ÖĞRENCİLERİ ARAŞTIRMA PROJELERİ DESTEKLEME PROGRAMI ARAŞTIRMA ÖNERİSİ FORMU",
        bold=True,
        size=11,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )

    add_section(doc, "A. GENEL BİLGİLER", level=1)
    add_kv_para(doc, "Başvuru Sahibinin Adı Soyadı", "[Proje yürütücüsü adı soyadı]")
    add_kv_para(
        doc,
        "Araştırma Önerisinin Başlığı",
        "Türkçe Hukuk Soru-Cevap Sistemlerinde Kaynak Temelli RAG ve İddia Doğrulama Katmanlarının Halüsinasyon Azaltımına Etkisi",
    )
    add_kv_para(doc, "Danışmanın Adı Soyadı", "[Danışman adı soyadı / unvanı]")
    add_kv_para(doc, "Araştırmanın Yürütüleceği Kurum/Kuruluş", "[Üniversite - Fakülte - Bölüm]")

    add_section(doc, "ÖZET", level=1)
    add_block(doc, "Özet", SUMMARY)
    add_kv_para(
        doc,
        "Anahtar Kelimeler",
        "Türkçe hukuk yapay zekası; RAG; halüsinasyon tespiti; kaynak doğrulama; bilişim hukuku",
    )

    add_section(doc, "1. ARAŞTIRMA ÖNERİSİNİN BİLİMSEL NİTELİĞİ", level=1)
    add_block(doc, "1.1 Konunun Önemi ve Araştırma Önerisinin Bilimsel Niteliği", SCIENTIFIC_QUALITY)
    add_block(doc, "Amaç ve Hedefler", OBJECTIVES)

    add_section(doc, "2. YÖNTEM", level=1)
    add_block(doc, "Yöntem", METHOD)

    add_section(doc, "3. PROJE YÖNETİMİ", level=1)
    add_section(doc, "3.1 Çalışma Takvimi", level=2)
    for idx, (date_range, activity, owner, success) in enumerate(WORK_ROWS, start=1):
        add_compact_item(
            doc,
            idx,
            date_range,
            [
                ("Faaliyet", activity),
                ("Sorumlu", owner),
                ("Başarı ölçütü ve katkısı", success),
            ],
        )

    add_section(doc, "3.2 Risk Yönetimi", level=2)
    for idx, (risk, probability, measure, fallback) in enumerate(RISK_ROWS, start=1):
        add_compact_item(
            doc,
            idx,
            risk,
            [
                ("Olasılık/Etki", probability),
                ("Tedbir", measure),
                ("B planı", fallback),
            ],
        )

    add_section(doc, "3.3 Araştırma Olanakları", level=2)
    for idx, (facility, detail, aim) in enumerate(FACILITY_ROWS, start=1):
        add_compact_item(
            doc,
            idx,
            facility,
            [
                ("Açıklama", detail),
                ("Projede kullanım amacı", aim),
            ],
        )

    add_section(doc, "4. YAYGIN ETKİ", level=1)
    add_kv_para(doc, "Bilimsel/Akademik Çıktılar", "Teknik rapor, deney veri şeması, karşılaştırmalı ölçüm tabloları, hata analizi ve sunum/poster çıktısı.")
    add_kv_para(doc, "Ekonomik/Ticari/Sosyal Çıktılar", "Kaynak şeffaflığı yüksek, hukuki tavsiye iddiası taşımayan, vatandaş odaklı güvenli hukuk bilgi erişimi yaklaşımı.")
    add_block(doc, "Yeni Proje(ler) Oluşturmasına Yönelik Çıktılar", IMPACT)

    add_section(doc, "5. BELİRTMEK İSTEDİĞİNİZ DİĞER KONULAR", level=1)
    add_block(doc, "Diğer Konular", OTHER_TOPICS)
    add_references(doc)

    for p in doc.paragraphs:
        apply_paragraph_format(p)

    props = doc.core_properties
    props.title = "2209-A Türkçe Hukuk RAG Araştırma Önerisi Taslağı"
    props.subject = "TÜBİTAK 2209-A araştırma önerisi"
    props.author = ""
    props.comments = ""
    props.keywords = "RAG, hukuk yapay zekası, halüsinasyon, kaynak doğrulama"
    props.last_modified_by = ""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
