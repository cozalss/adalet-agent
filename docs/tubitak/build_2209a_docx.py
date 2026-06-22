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
OUT = ROOT / "docs" / "tubitak" / "2209-A_Turkce_Hukuk_RAG_Basvuru_Taslagi.docx"

FONT = "Arial"
SIZE = Pt(9)
FULL_WIDTH_TWIPS = 9360

PROJECT_TITLE = (
    "Türkçe Hukuk Soru-Cevap Sistemlerinde Kaynak Temelli RAG ve İddia "
    "Doğrulama Katmanlarının Halüsinasyon Azaltımına Etkisi"
)


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
    # Spacing'i doğrudan ayarla — apply_paragraph_format run'ların puntosunu SIZE(9)'a
    # sıfırlıyor; özel punto (kapak başlığı 16pt vb.) korunsun diye run'ı sonra ekle.
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    if text:
        r = p.add_run(text)
        r.font.name = FONT
        r.font.size = Pt(size)
        r.bold = bold
    if align is not None:
        p.alignment = align
    return p


def add_section(doc: Document, title: str, level: int = 1):
    p = doc.add_paragraph()
    r = p.add_run(title)
    r.font.name = FONT
    r.font.size = Pt(11 if level == 1 else 10)
    r.bold = True
    r.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5B)
    p.paragraph_format.space_before = Pt(10 if level == 1 else 6)
    p.paragraph_format.space_after = Pt(5)
    if level == 1:
        add_section_rule(p, color="1B3A5B", size="14")
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
    add_section(doc, "7. EKLER", level=1)
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
    if title:  # boş başlık → tekrar etme (bölüm başlığıyla aynıysa atla)
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

Ön çalışma kapsamında bir araştırma prototipi (hibrit arama, kaynak gösterimli cevap, çok katmanlı risk koruması) ve 159.362 vektörlük hukuk külliyatı hazırlanmıştır. Geliştirici tarafından küçük iç test setlerinde umut verici ölçümler gözlenmiştir (örn. yüksek halüsinasyon yakalama, uydurma eşik F1 ≈ 0,98); ancak bu ön ölçümler küçük, tek-kişi etiketli ve bağımsız doğrulaması olmadığından KANIT DEĞİL, yalnızca araştırmayı tetikleyen MOTİVASYON sayılmalıdır. Proje, bu ön bulguların bağımsız, insan-etiketli, kör ve istatistiksel olarak geçerli bir çerçevede korunup korunmadığını sınar; insan etiketli altın veri seti, otomatik ölçümler, hata analizi ve tekrarlanabilir deney raporuyla akademik araştırma çıktısı üretir.

Beklenen çıktı; hukuki tavsiye vermeyen, kaynak şeffaflığını öne çıkaran, riskli cevapları reddedebilen ve Türkçe hukuk yapay zekası çalışmalarında kullanılabilecek ölçülebilir bir yöntem önerisidir.
"""

SCIENTIFIC_QUALITY = """
Hukuk alanında büyük dil modellerinin kullanımı, vatandaşların hak arama süreçleri ve bilgiye erişimi açısından önemli fırsatlar sunarken, hatalı veya kaynaksız cevap üretme riski nedeniyle yüksek toplumsal sorumluluk gerektirir. Özellikle Türkçe hukuk metinlerinde mevzuat, içtihat ve idari görüşlerin dili; genel amaçlı modellerin eğitim dağılımından farklıdır. Bu durum, modelin doğru görünen ancak kaynağı bulunmayan hukuki iddialar üretmesine, uygulanmayan süre veya parasal eşikler uydurmasına ve kullanıcının yanlış yönlendirilmesine yol açabilir.

Literatürde RAG yaklaşımı, dil modelinin cevabını dış bilgi kaynaklarıyla destekleyerek güncellik ve izlenebilirlik sorunlarını azaltmayı hedefler. Ancak yalnızca ilgili belge getirmek, cevaptaki her cümlenin gerçekten o kaynak tarafından desteklendiğini garanti etmez. Hukuk gibi riskli alanlarda araştırma problemi bu nedenle "belge bulundu mu?" sorusundan "cevaptaki her hukuki iddia kanıtla destekleniyor mu?" sorusuna taşınmalıdır.

İddia/faktualite doğrulama için İngilizce açık-alanda yerleşik bir literatür vardır: atomik olgu doğrulama (FActScore, Min vd., 2023), düzelt-ve-atfet (RARR, Gao vd., 2023) ve cevaba atıf ekleme (ALCE, Gao vd., 2023). Bu yöntemler temel alınacak; ancak hiçbiri Türkçe hukuk diline ve hukuk alanının özel gereksinimlerine (kaynak-zorunluluğu, kaynakla ÇELİŞEN iddianın tespiti ve riskli durumda GÜVENLİ RET) uyarlanmamıştır. Hukuki halüsinasyonu profilleyen öncü çalışma (Dahl vd., 2024) ağırlıklı olarak İngilizce ve ABD/ortak hukuk bağlamındadır; RAG için otomatik değerlendirme (RAGAS) Türkçe hukukta kalibre edilmemiştir.

Bu projenin somut özgün katkısı şudur: Bilgimiz dahilinde, Türkçe hukuk soru-cevabı için iddia düzeyinde kaynak-temellendirme (claim-level grounding) ölçen, kamuya açık ve tekrarlanabilir bir kıyas (benchmark), etiketli değerlendirme seti ve hata taksonomisi bulunmamaktadır; bu eksik, proje kapsamında yapılacak sistematik literatür taramasıyla teyit edilip belgelenecektir. Proje, atfetme yöntemlerini hukuk domainine taşırken çelişki-tespiti ve güvenli-ret katmanını ekler ve etkisini kontrollü deneyle ölçer. Açıkça belirtmek gerekir ki bu bileşenler (atfetme, NLI-çelişki, abstention) literatürde ayrı ayrı bilinmektedir; özgün katkı yeni bir algoritma icadı değil, bunların Türkçe hukuk bağlamında TEK bir değerlendirme çerçevesinde birleştirilmesi, etkilerinin kontrollü ablasyonla AYRIŞTIRILMASI ve sonucun açık, tekrarlanabilir bir kıyas olarak paylaşılmasıdır. Ayrıca Türkçe hukuk dili teknik olarak ayırt edici bir NLP zorluğu doğurur: madde-fıkra-bent atıf morfolojisi, içtihat atıf belirsizliği ve mevzuatın mülga/değişiklik katmanları, genel-amaçlı modelin yüzeysel eşleşmesini yanıltır.

Araştırma önerisinin bilimsel niteliği üç noktada yoğunlaşmaktadır. Birincisi, Türkçe ve hukuk alanına özgü değerlendirme senaryoları oluşturulacaktır. İkincisi, klasik RAG hattı ile iddia doğrulama katmanlı RAG hattı aynı soru setleri üzerinde karşılaştırılacaktır. Üçüncüsü, sistem sadece nihai cevap kalitesine göre değil; kaynak kapsama, iddia desteği, uydurma eşik yakalama, yanlış ret oranı, gecikme ve maliyet gibi çok boyutlu ölçütlerle değerlendirilecektir.

Ön çalışmada sekiz hukuk alanını kapsayan bir araştırma prototipi geliştirilmiş, 159.362 vektörlük kamu hukuku külliyatı indekslenmiş, hibrit arama ve tekrar sıralama bileşenleri denenmiştir. Geliştirici tarafından hazırlanan küçük iç test setlerinde umut verici ölçümler gözlenmiştir (örn. retrieval domain@5 ≈ %97; risk-koruma testinde yüksek yakalama; uydurma eşik F1 ≈ 0,98). ANCAK bu ön ölçümler metodolojik olarak GÜVENİLİR SAYILMAMALIDIR: test setleri küçük, etiketleme tek kişinin öznel kararına dayalı, bağımsız insan doğrulaması ve kontaminasyon (test sızıntısı) kontrolü yoktur. Dolayısıyla bu sayılar bir kanıt değil, yalnızca araştırmayı tetikleyen MOTİVASYON olarak ele alınır. Projenin asıl bilimsel sorusu tam da buradan doğar: Bu umut verici ön bulgular; bağımsız, insan-etiketli, kör (blind), alanlar-arası dengeli ve istatistiksel olarak geçerli bir değerlendirme çerçevesinde KORUNUR MU; korunmazsa hangi hata türleri ortaya çıkar? TÜBİTAK projesi mevcut sistemi belgelemeyi değil, bu soruyu kontrollü deneyle sınamayı ve sonucu tekrarlanabilir bir çerçeveyle paylaşmayı hedefler.

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

Başarı ölçütü, belirli bir sonucu garanti etmek değil, etkiyi GEÇERLİ biçimde ÖLÇEBİLMEKTİR: (i) birincil hipotezi (iddia-destek oranı, doğrulama açık vs kapalı) yaklaşık 30 puanlık bir etkiyi %80 istatistiksel güçle saptayabilecek, ön-kayıtlı bir analiz planıyla test etmek; (ii) halüsinasyon yakalama, yanlış ret, kaynak doğruluğu ve maliyet ölçütlerini güven aralıklarıyla raporlamak; (iii) deneyleri yeniden üretilebilir betikler ve açık veriyle paylaşmaktır. Etki beklenenden küçük çıksa bile (örn. 30 yerine 15 puan) bu geçerli bir bilimsel bulgudur ve proje başarısız sayılmaz; başarısızlık yalnızca etkinin güçsüz veya yanlı tasarım nedeniyle ölçülememesidir.
"""

METHOD = """
Araştırma yöntemi kontrollü karşılaştırmalı deney tasarımına dayanır. Bağımsız değişkenler; arama stratejisi (hibrit arama, tekrar sıralama, isteğe bağlı HyDE/multi-query), LLM sağlayıcısı (OpenAI ana hat, yerel Qwen opsiyonel hat) ve doğrulama durumu (doğrulama kapalı/açık, katman seviyesi) olarak belirlenecektir. Bağımlı değişkenler; halüsinasyon yakalama, yanlış ret, kaynak doğruluğu, iddia desteği, cevap kalitesi, gecikme ve maliyettir.

Veri hazırlama aşamasında yalnızca kamuya açık mevzuat, yargı kararları ve idari görüşler kullanılacak; kullanıcı verisi veya özel kişisel veri dahil edilmeyecektir. Yargı kararlarındaki kişisel veriler (taraf adı, TCKN, adres) otomatik PII maskeleme ve manuel kontrolle temizlenecektir. Sorular anonim/sentetik hazırlanacaktır. Etik bakımından çalışma yalnızca kamuya açık metin ve sentetik soru kullandığından kurul MUAFİYETİ beklenmektedir; muafiyet/onay başvurusu Ay 1'de proaktif yapılacak, sonuç beklenirken kod/indeks hazırlığı sürdürülecek, insan değerlendirmesi etik durum netleşmeden başlatılmayacaktır.

Etiketlerin HUKUKİ DOĞRULUĞU güvencesi kritik bir tasarım unsurudur: soru/etiket şeması ile "uydurma eşik riski" ve "cevaplanabilirlik" gibi kategoriler, bir hukuk öğrencisi/uzmanı (gönüllü) ve birincil hukuk kaynaklarıyla teyit edilecek; yazılım ekibinin etiketi tek başına nihai sayılmayacaktır. Her soru için beklenen hukuk alanı, kaynak türü, cevaplanabilirlik durumu ve risk etiketi kaydedilir. İnsan değerlendirmesi alt kümesinde (altın setin ~%30'u) ikinci bağımsız değerlendirici (bölümden gönüllü lisans öğrencisi veya danışman yönlendirmesiyle bir hukuk öğrencisi) çift-etiketleme yapacak; tüm set değil, bu temsilî alt küme çift-etiketlenecektir. Uyuşmazlıklar açıklama kılavuzuna göre giderilecektir.

Deney hattı şu adımlardan oluşur: kullanıcının sorusu alınır; alan sınıflandırması ve güvenlik kontrolü yapılır; ilgili hukuk kaynakları hibrit arama ile getirilir; model kaynaklara dayanarak taslak cevap üretir; cevap hukuki iddialara ayrılır; her iddia getirilen kaynak parçalarıyla doğrulanır; desteklenmeyen, çelişkili veya uydurma görünen iddialar işaretlenir; nihai cevap kaynaklı, sınırlı ve hukuki danışmanlık vermeyen formatta üretilir. Güvenli-ret/ek-bilgi kararı operasyonel bir kurala bağlanır: bir iddianın NLI-çelişki skoru τ eşiğini aşarsa veya kaynak-kapsama skoru c eşiğinin altındaysa iddia düşürülür; cevabın bütününde desteklenen-iddia oranı bir alt eşiğin altına inerse sistem cevap üretmek yerine güvenli-ret veya netleştirme sorusu döndürür. Eşikler (τ, c ve oran tabanı) kör kalibrasyon alt-kümesinde belirlenir ve test setinde sabit tutulur. Ayrıca Türkçe hukuk diline özgü zorluklar değerlendirme setinde ayrı alt-kategoriler olarak işaretlenir (örn. mülga/değişmiş madde içeren tuzak sorular, içtihat atıf belirsizliği), böylece bu zorlukların hata oranına etkisi ölçülebilir.

Analiz aşamasında doğrulama kapalı ve doğrulama açık koşullar aynı soru setinde karşılaştırılacaktır. Sayısal sonuçlar Wilson güven aralıkları, eşleşmiş karşılaştırmalar ve hata türlerine göre ayrıştırılmış tablolarla raporlanacaktır. Otomatik ölçümlerin yanı sıra insan değerlendirmesiyle kaynak uygunluğu, cevap faydası ve riskli kesinlik kontrol edilecektir. Bu sayede yalnızca "sistem çalışıyor" değil, hangi bileşenin hangi hata türünü azalttığı gösterilecektir.

Ön çalışma altyapısı bu yöntemi uygulamaya hazırdır: FastAPI tabanlı backend, LangGraph tarzı çok adımlı ajan akışı, Qdrant vektör indeksi, BGE-M3/Mürşit tabanlı arama denemeleri, Supabase kimlik/veri yönetimi, React arayüzü ve otomatik test kapıları bulunmaktadır. Mevcut doğrulama komutlarında üretime hazırlık, dokümantasyon tutarlılığı, canlı entegrasyon sözleşmeleri ve risk koruması kontrolleri başarılı çalışmıştır.
"""

OTHER_TOPICS = """
Mevcut kod tabanı bir araştırma deney platformudur: kontrollü deneylerin yürütüleceği altyapıyı sağlar, araştırma çıktısının kendisi değildir. Projenin bilimsel katkısı sistemin varlığı değil; iddia-düzeyi doğrulamanın halüsinasyon azaltımına etkisinin bağımsız, insan-kalibreli ve istatistiksel olarak geçerli biçimde ölçülmesi ve tekrarlanabilir bir kıyas (benchmark) olarak paylaşılmasıdır. Başlık, özet ve yöntem ticari ad/ürün yerine bu bilimsel probleme odaklanmıştır.

Üretken yapay zeka kullanımı sorumlu biçimde yönetilecektir. Model çıktıları tek başına hukuki tavsiye olarak sunulmayacak, kaynakla desteklenmeyen iddialar reddedilecek ve proje çıktılarında yapay zeka kullanımının sınırları açıkça belirtilecektir. OpenAI API ana deney hattı olarak seçilmiştir; çünkü yerel Qwen dağıtımı GPU, CUDA/sürücü uyumluluğu, bellek ve performans açısından proje takvimi için risk taşır. Yerel model karşılaştırması, başarı için zorunlu değil opsiyonel araştırma genişletmesi olarak planlanmıştır.

Bütçe toplam 10.300 TL'dir (2209-A 2025 üst limiti 12.000 TL'nin altında); çoğunlukla hizmet alımı/API kredisi, geçici bulut işlem ve sarf giderlerine ayrılmıştır ve tutarlar ihtiyaçtan türetilmiştir (ayrıntı/gerekçe için Bölüm 5). Kongre katılımı, yayın ücreti, konaklama, yolluk ve gündelik gibi program dışı kalemler bütçeye konulmamıştır.
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
    ("Kişisel veri veya etik onay riski", "Düşük/Orta", "Yalnızca kamuya açık kaynak + anonim/sentetik soru; yargı kararlarında PII maskeleme. Etik kurul muafiyet başvurusu Ay 1'de PROAKTİF yapılır (muafiyet beklenir).", "Muafiyet yerine onay gerekirse: kod/indeks IP'leri onaydan bağımsız ilerler; insan değerlendirmesi IP'sindeki ~2 haftalık esneklik gecikmeyi soğurur."),
    ("Hukuk teyitçisi / ikinci bağımsız değerlendirici tedarik edilememesi", "Orta", "Danışman aracılığıyla Hukuk Fakültesi'nden bir öğrenci/araştırma görevlisiyle ön mutabakat hedeflenir; çift-etiketleme altın setin ~%30'uyla sınırlı tutulur.", "Bulunamazsa: birincil-kaynak + danışman ikili teyidi, tüm 'desteklenmedi' kararlarında ikinci-tur kör gözden geçirme ve LLM-judge'ın çapraz-doğrulayıcı olarak yükseltilmesi; alan-uzmanı teyidi olmadan etiket yayımlanmaz."),
    ("Değerlendirme seti hazırlığının (Ay 2-3) sarkması", "Orta", "Soru/etiket şeması Ay 1'de hazırlanır; veri tabana (150 soru) öncelik verilir, genişletme kademelidir.", "Gecikirse birincil hipotez 150 soruyla test edilir; 300'e genişletme Ay 8-9'a kaydırılır (güç analizi tabanı korunur)."),
]

FACILITY_ROWS = [
    ("Mevcut araştırma prototipi ve kod tabanı", "FastAPI backend, React arayüz, Supabase kimlik/veri yönetimi, Qdrant vektör indeksi, otomatik test ve ölçüm komutları hazırdır.", "Veri işleme, deney yürütme ve sonuç toplama için kullanılacaktır."),
    ("Kamuya açık hukuk kaynakları", "Mevzuat, yargı kararları ve idari görüşlerden oluşan ön indeks; 159.362 vektörlük mevcut çalışma kopyası bulunmaktadır.", "Retrieval ve kaynak doğrulama deneylerinin temel veri tabanını oluşturacaktır."),
    ("Model ve hesaplama olanakları", "OpenAI API ana yürütme hattı; yerel GPU/CPU ortamı ve Qwen kurulumu opsiyonel karşılaştırma için değerlendirilecektir.", "Kararlı deney üretimi ve sınırlı maliyetli model karşılaştırması sağlar."),
    ("Üniversite danışmanlığı ve çalışma ortamı", "Danışman akademik denetimi, etik uygunluk kontrolü ve raporlama geri bildirimi sağlayacaktır.", "Araştırma tasarımı, değerlendirme ve sonuçların akademik niteliğini güçlendirir."),
    ("Hukuki doğruluk teyidi (gönüllü hukuk öğrencisi/uzmanı)", "Etiket şemasının ve risk/cevaplanabilirlik kategorilerinin hukuki doğruluğu birincil kaynaklarla teyit edilecek; ikinci bağımsız etiketleyici olarak da değerlendirilebilir.", "Yazılım ekibinin hukuk uzmanı olmamasından doğan etiket-geçerliği riskini düşürür."),
]

REFERENCES = [
    "Lewis, P. vd. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. arXiv:2005.11401. https://arxiv.org/abs/2005.11401",
    "Gao, L. vd. (2022). Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE). arXiv:2212.10496. https://arxiv.org/abs/2212.10496",
    "Chen, J. vd. (2024). BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings. arXiv:2402.03216. https://arxiv.org/abs/2402.03216",
    "Dahl, M. vd. (2024). Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models. arXiv:2401.01301. https://arxiv.org/abs/2401.01301",
    "Es, S. vd. (2023). RAGAS: Automated Evaluation of Retrieval Augmented Generation. arXiv:2309.15217. https://arxiv.org/abs/2309.15217",
    "Min, S. vd. (2023). FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation. arXiv:2305.14251. https://arxiv.org/abs/2305.14251",
    "Gao, L. vd. (2023). RARR: Researching and Revising What Language Models Say, Using Language Models. arXiv:2210.08726. https://arxiv.org/abs/2210.08726",
    "Gao, T. vd. (2023). Enabling Large Language Models to Generate Text with Citations (ALCE). arXiv:2305.14627. https://arxiv.org/abs/2305.14627",
    "He, P. vd. (2021). DeBERTa: Decoding-enhanced BERT with Disentangled Attention. arXiv:2006.03654. https://arxiv.org/abs/2006.03654",
    "TÜBİTAK. 2209-A Üniversite Öğrencileri Araştırma Projeleri Destekleme Programı. https://tubitak.gov.tr/tr/burslar/lisans-onlisans/destek-programlari/2209-universite-ogrencileri-arastirma-projeleri-destekleme-programi",
    "TÜBİTAK. 2209-A 2025 Yılı Çağrı Duyurusu ve Araştırma Önerisi Formu. https://tubitak.gov.tr/tr/duyuru/2209-universite-ogrencileri-arastirma-projeleri-destekleme-programi-2025-yili-cagrisi-acildi",
    "TÜBİTAK. Öncelikli Alanlar Listesi 2025. https://tubitak.gov.tr/sites/default/files/2025-07/Oncelikli_Alanlar_2025-2.pdf",
]


LIT_GAP_ROWS = [
    ("Klasik RAG (Lewis vd., 2020)", "İlgili belge getirir; cevaptaki her cümlenin o belgece desteklendiğini GARANTİ ETMEZ.", "Belge düzeyinden iddia düzeyi doğrulamaya geçilir; her hukuki iddia kaynak parçasıyla eşleştirilir."),
    ("Hukuki halüsinasyon profili (Dahl vd., 2024)", "İngilizce / ABD-ortak hukuk odaklı; Türkçe medeni-idari hukuka uyarlanmamış.", "Türkçe mevzuat ve yargı kararlarında, sekiz hukuk alanında halüsinasyon ölçümü yapılır."),
    ("Otomatik RAG değerlendirmesi (RAGAS, Es vd., 2023)", "İngilizce ağırlıklı; Türkçe hukuk iddia-temellendirmesinde doğrulanmamış.", "Türkçe hukuk için iddia-destek, kaynak doğruluğu ve uydurma-yakalama ölçütleri uyarlanır ve insan etiketiyle kalibre edilir."),
    ("Faktualite/atfetme (FActScore, RARR, ALCE)", "İngilizce açık-alan; hukuk-özgü kaynak-zorunluluğu, çelişki-tespiti ve güvenli-ret YOK.", "Atfetme yaklaşımı hukuk domainine taşınır; çelişen iddia tespiti + riskli durumda güvenli-ret katmanı eklenir."),
    ("Türkçe hukuk NLP", "Kamuya açık, tekrarlanabilir iddia-düzeyi kaynak-temellendirme kıyası (benchmark) bilgimiz dahilinde YOK.", "Etiketli/yarı-etiketli değerlendirme seti, deney betikleri ve hata taksonomisi açık biçimde paylaşılır."),
]

VARIABLES_ROWS = [
    ("Bağımsız", "Doğrulama durumu", "Kapalı / Açık (iddia-düzeyi NLI+kaynak eşleştirme); ana karşılaştırma."),
    ("Bağımsız", "Arama stratejisi", "Hibrit arama; +tekrar sıralama; +HyDE/çoklu-sorgu (kademeli)."),
    ("Bağımsız", "LLM sağlayıcısı", "OpenAI ana hat; yerel Qwen opsiyonel hat (imkân varsa)."),
    ("Bağımlı", "Halüsinasyon yakalama oranı", "Uydurma/desteksiz iddia içeren cevaplarda doğru ret oranı (recall)."),
    ("Bağımlı", "Yanlış ret oranı", "Temiz ve cevaplanabilir sorularda gereksiz ret (false positive)."),
    ("Bağımlı", "İddia-destek oranı", "Cevaptaki iddialardan kaynak parçasıyla desteklenenlerin oranı."),
    ("Bağımlı", "Kaynak doğruluğu / kapsama", "Getirilen kaynakların ilgili maddeyi içerme oranı (domain@k, MRR)."),
    ("Bağımlı", "Gecikme ve maliyet", "Cevap başına süre (ms) ve API/token maliyeti."),
    ("Kontrol", "Hukuk alanı, soru tipi, zorluk", "Sekiz alan; tanımsal/olgusal/alan-dışı/uydurma-eşik etiketleri dengeli tutulur."),
]

STATS = """
Birincil sonuç ölçütü ÖNCEDEN tek olarak belirlenmiştir: iddia-destek oranı (doğrulama açık vs kapalı, aynı sorularda eşleştirilmiş McNemar testi). Diğer altı ölçüt (halüsinasyon yakalama, yanlış ret, kaynak doğruluğu, gecikme, maliyet ve alan-bazlı kırılımlar) ikincil/keşifseldir; bunlarda çoklu karşılaştırma için Holm-Bonferroni düzeltmesi uygulanacaktır. Bu ayrım, aile-bazında yanlış-pozitif (FWER) riskini denetler.

Örneklem büyüklüğü güç (power) analiziyle gerekçelendirilir: McNemar gücü uyuşmazlık (discordant) çiftlerinin sayısına bağlıdır. Çalışma varsayımı olarak baz iddia-destek oranı ≈ %55, doğrulama açıkken ≈ %85 (≈30 puan etki) ve beklenen discordant çift oranı ≈ %25-30 alınır; α=0,05 ve güç=0,80 için gereken çift sayısı statsmodels/G*Power ile türetilir ve yaklaşık 130-160 soruya karşılık gelir (varsayımlara duyarlılık için %20/%25/%30 discordant senaryoları ayrıca raporlanır). Bu nedenle taban 150 soruya demirlenir; üst sınır (300) bütçe/zaman elverirse keşifsel genişletmedir. Birincil hipotez 150 soruyla test edilebilir; genişletme keşifseldir.

İkili oranlar Wilson güven aralıklarıyla; sürekli ölçütler (gecikme, maliyet) eşleştirilmiş yapı korunarak çift-bazlı 10.000 yeniden örneklemeli bootstrap güven aralıklarıyla raporlanır. Etki büyüklüğü mutlak fark (yüzde puan) + güven aralığı olarak verilir (yalnız p-değeri değil).

Ölçüm geçerliği güvenceleri: (a) İddia ayrıştırma (claim segmentation) güvenilirliği, altın-set alt kümesinde iki bağımsız insan ayrıştırması arası uyumla (F1/kappa) ölçülür. (b) Otomatik iddia-destek ölçümünün insan altın-setle Pearson/Spearman korelasyonu raporlanır; LLM-judge kullanılırsa cevabı üreten modelden FARKLI aileden bir doğrulayıcı seçilir (self-preference yanlılığı kontrolü). (c) Değerlendiriciler arası uyum, prevalans dengesizliğine karşı Cohen kappa yanında gözlenen uyum yüzdesi + PABAK/Gwet AC1 ile birlikte verilir. (d) Alan/soru-tipi/zorluk için tabakalı (stratified) örnekleme; "zorluk" tek-madde vs çok-madde/çok-kaynak gerektiren soru olarak operasyonel tanımlanır; alanlar-arası heterojenlik etkileşim analiziyle incelenir.

Üç ek tasarım kararı analiz geçerliğini korur: (e) Birincil analiz birimi SORU/cevaptır; iddia-düzeyi oranlar soru içinde toplulaştırılır (cevap içi iddiaların küme korelasyonu nedeniyle iddia bağımsız sayılmaz), ardından eşleştirilmiş test uygulanır. (f) Goodhart riskine karşı iddia-destek oranı tek başına değil, yanlış-ret ve cevap-faydası eş-eşikte tutularak yorumlanır (sistem iddiaları kırparak oranı yapay şişiremez). (g) İnsan etiketçi bir iddianın desteğini, getirilen parçalardan BAĞIMSIZ olarak birincil hukuk kaynağına karşı değerlendirir; retrieval kapsama ayrı ölçülür (grounding ile retrieval karıştırılmaz). Çoklu LLM-sağlayıcı ve arama-varyantı hücreleri yalnızca keşifsel/tanımlayıcı raporlanır; bu hücrelerde hipotez testi yapılmaz.
"""

BUDGET_ROWS = [
    ("Hizmet alımı — LLM API kredisi (OpenAI)", "Ana deney hattı: taslak üretimi, iddia çıkarımı, doğrulama ve otomatik değerlendirme çağrıları; gpt-4o-mini ağırlıklı, önbellekleme + kademeli artışla sınırlı (alt-hesap için bkz. açıklama).", "6.000"),
    ("Hizmet alımı — Bulut işlem (geçici)", "Yalnızca insan deneyi/koşu pencerelerinde geçici GPU/CPU bulut (kalıcı indeks yereldir): ~60 saat × ~30 TL/saat.", "1.800"),
    ("Sarf / yazılım hizmeti", "Veri etiketleme yardımcı araçları, depolama, küçük ölçekli yazılım/abonelik.", "1.200"),
    ("Yedek / öngörülemeyen", "API fiyat değişimi, ek deney koşusu veya bulut aşımı için çok-amaçlı pay.", "1.300"),
    ("TOPLAM", "İhtiyaçtan türetilmiştir; 2209-A 2025 üst limitinin (12.000 TL) ALTINDADIR.", "10.300"),
]

BUDGET_NOTE = """
API kredisi kaba tahmini: birincil deney 150 soru (genişlerse 300) × ~3 LLM çağrısı (taslak, iddia çıkarımı, doğrulama) × deney kolları (doğrulama açık/kapalı + arama varyantları, ~4) × tekrar (~2) ≈ 3.600-7.200 çağrı; soru başına ortalama ~3.000 girdi + ~600 çıktı token ile gpt-4o-mini ağırlıklı (zor alt-kümede gpt-4o) ve önbellekleme/kademeli artış uygulanarak tahmini ≈ 6.000 TL. Üst sınır riski çok-amaçlı yedek (1.300 TL) ile karşılanır. Deney maliyeti Ay 4-5'te yoğunlaşır; Ay 8-9 maliyet/gecikme analizi ve Ay 10-12 raporlama için kalan kredi ayrılır.

Toplam bütçe 10.300 TL'dir; 2209-A 2025 üst limitinin (12.000 TL) ALTINDA tutulmuştur ve tutarlar ihtiyaçtan türetilmiştir (tavandan değil). Program dışı kalemler (kongre/konferans, yayın/patent, konaklama, gündelik/yemek) dahil edilmemiştir. Kalıcı vektör indeksi yerel olduğundan bulut kalemi yalnızca geçici deney koşu pencereleri içindir.
"""


def add_budget(doc: Document):
    add_section(doc, "5. BÜTÇE VE GEREKÇESİ", level=1)
    add_data_table(
        doc,
        ["Gider Kalemi", "Açıklama / Gerekçe", "Tahmini Tutar (TL)"],
        [list(row) for row in BUDGET_ROWS],
        [2600, FULL_WIDTH_TWIPS - 2600 - 1500, 1500],
    )
    add_block(doc, "Bütçe Açıklaması", BUDGET_NOTE)


ASSETS = ROOT / "docs" / "tubitak" / "assets"

NAVY_RGB = RGBColor(0x1B, 0x3A, 0x5B)
TEAL_RGB = RGBColor(0x25, 0x6E, 0x8E)
GOLD_RGB = RGBColor(0xC4, 0x9A, 0x3A)
GREY_RGB = RGBColor(0x5B, 0x6B, 0x7B)
WHITE_RGB = RGBColor(0xFF, 0xFF, 0xFF)


def add_figure(doc: Document, filename: str, width_in: float = 6.3):
    path = ASSETS / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Görsel '{filename}' bulunamadı ({ASSETS}). Önce make_figures.py çalıştır."
        )
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Inches(width_in))
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(7)
    return p


def add_section_rule(paragraph, color="1B3A5B", size="12"):
    p_pr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "3")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    p_pr.append(pbdr)


def add_field(paragraph, instr: str):
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    rfonts.set(qn("w:ascii"), FONT)
    rpr.append(rfonts)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = "1"
    run.append(t)
    fld.append(run)
    paragraph._p.append(fld)


def setup_footer(doc: Document, left_text: str):
    section = doc.sections[0]
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.text = ""
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_section_rule(p, color="C9D6E3", size="6")  # ince üst çizgi hissi
    r = p.add_run(left_text + "    ·    Sayfa ")
    apply_run_font(r)
    r.font.size = Pt(7.5)
    r.font.color.rgb = GREY_RGB
    add_field(p, "PAGE")


def add_band(doc: Document, text: str, fill: str = "1B3A5B", tcolor=WHITE_RGB, size: float = 13):
    """Tam genişlikte renkli başlık bandı (tek hücreli gölgeli tablo)."""
    table = doc.add_table(rows=1, cols=1)
    set_table_width(table, [FULL_WIDTH_TWIPS])
    cell = table.cell(0, 0)
    shade_cell(cell, fill)
    set_cell_margins(cell, 140)
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.font.name = FONT
    r.font.size = Pt(size)
    r.bold = True
    r.font.color.rgb = tcolor
    # apply_paragraph_format KULLANMA: run puntosunu SIZE(9)'a sıfırlar (ECC HIGH).
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    # tablo kenarlığını gizle (sadece dolgu görünsün)
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "none")
        borders.append(e)
    tbl_pr.append(borders)
    return table


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

    add_band(doc, "TÜBİTAK 2209-A — ÜNİVERSİTE ÖĞRENCİLERİ ARAŞTIRMA PROJELERİ DESTEKLEME PROGRAMI",
             fill="1B3A5B", size=10.5)
    p = add_para(doc, "ARAŞTIRMA ÖNERİSİ FORMU", bold=True, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)
    p.runs[0].font.color.rgb = TEAL_RGB
    p.paragraph_format.space_before = Pt(3)

    add_para(doc, "", size=12)
    p = add_para(doc, "ARAŞTIRMA ÖNERİSİNİN BAŞLIĞI", bold=True, size=8.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    p.runs[0].font.color.rgb = GREY_RGB
    p = add_para(doc, PROJECT_TITLE, bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER)
    p.runs[0].font.color.rgb = NAVY_RGB
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    p.paragraph_format.space_after = Pt(16)

    add_key_value_table(doc, [
        ("Başvuru Sahibi (Proje Yürütücüsü)", "Cem ÖZAL"),
        ("Danışman", "Dr. Öğr. Üyesi Bilgin AVENOĞLU"),
        ("Kurum / Birim", "Çankaya Üniversitesi – Mühendislik Fakültesi – Yazılım Mühendisliği Bölümü"),
        ("Öncelikli Alan", "Bilişim Teknolojileri / Yapay Zeka"),
    ])

    add_para(doc, "", size=14)
    p = add_para(doc, "2026 Yılı  —  [Çağrı dönemine göre güncellenecek] Dönem Başvurusu",
                 bold=True, size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    p.runs[0].font.color.rgb = NAVY_RGB
    p = add_para(doc, "Form Arial 9 punto, ekler hariç en fazla 20 sayfa olacak biçimde hazırlanmıştır.",
                 size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    p.runs[0].font.color.rgb = GREY_RGB
    doc.add_page_break()

    add_para(
        doc,
        "2209-A ÜNİVERSİTE ÖĞRENCİLERİ ARAŞTIRMA PROJELERİ DESTEKLEME PROGRAMI ARAŞTIRMA ÖNERİSİ FORMU",
        bold=True,
        size=11,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )

    add_section(doc, "A. GENEL BİLGİLER", level=1)
    add_kv_para(doc, "Başvuru Sahibinin Adı Soyadı", "Cem ÖZAL")
    add_kv_para(doc, "Araştırma Önerisinin Başlığı", PROJECT_TITLE)
    add_kv_para(doc, "Danışmanın Adı Soyadı", "Dr. Öğr. Üyesi Bilgin AVENOĞLU")
    add_kv_para(
        doc,
        "Araştırmanın Yürütüleceği Kurum/Kuruluş",
        "Çankaya Üniversitesi - Mühendislik Fakültesi - Yazılım Mühendisliği Bölümü",
    )
    add_kv_para(doc, "Öncelikli Alan", "Bilişim Teknolojileri / Yapay Zeka (bilişim hukuku ile ilişkili)")

    add_section(doc, "ÖZET", level=1)
    add_block(doc, "", SUMMARY)
    add_kv_para(
        doc,
        "Anahtar Kelimeler",
        "Türkçe hukuk yapay zekası; RAG; halüsinasyon tespiti; kaynak doğrulama; bilişim hukuku",
    )

    add_section(doc, "1. ARAŞTIRMA ÖNERİSİNİN BİLİMSEL NİTELİĞİ", level=1)
    add_block(doc, "1.1 Konunun Önemi ve Problem Tanımı", SCIENTIFIC_QUALITY)
    add_para(doc, "1.2 Literatürdeki Boşluk ve Projenin Özgün Katkısı", bold=True, size=9)
    add_data_table(
        doc,
        ["Mevcut Yaklaşım", "Sınır / Boşluk", "Bu Projenin Özgün Katkısı"],
        [list(row) for row in LIT_GAP_ROWS],
        [2700, 3100, FULL_WIDTH_TWIPS - 2700 - 3100],
    )
    add_para(doc, "1.3 Ön Çalışma Bulguları", bold=True, size=9)
    add_para(doc, "Geliştirilen araştırma prototipinde elde edilen ölçümler, önerilen yaklaşımın uygulanabilirliğini göstermektedir (Şekil 1).", size=9)
    add_figure(doc, "fig_results.png", width_in=5.5)
    add_block(doc, "1.4 Amaç ve Hedefler", OBJECTIVES)

    add_section(doc, "2. YÖNTEM", level=1)
    add_block(doc, "2.1 Araştırma Tasarımı ve Akış", METHOD)
    add_para(doc, "Önerilen ajan hattının uçtan uca akışı Şekil 2'de özetlenmiştir.", size=9)
    add_figure(doc, "fig_architecture.png", width_in=6.3)
    add_para(doc, "2.2 Değişkenler", bold=True, size=9)
    add_data_table(
        doc,
        ["Tür", "Değişken", "Seviyeler / Ölçüm"],
        [list(row) for row in VARIABLES_ROWS],
        [1400, 2700, FULL_WIDTH_TWIPS - 1400 - 2700],
    )
    add_para(doc, "Deney, aynı soru seti üzerinde doğrulama kapalı (Kol A) ve açık (Kol B) koşullarını eşleştirilmiş biçimde karşılaştırır (Şekil 3).", size=9)
    add_figure(doc, "fig_experiment.png", width_in=6.3)
    add_block(doc, "2.3 İstatistiksel Çözümleme", STATS)

    add_section(doc, "3. PROJE YÖNETİMİ", level=1)
    add_section(doc, "3.1 Çalışma Takvimi", level=2)
    add_figure(doc, "fig_gantt.png", width_in=6.3)
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
    add_kv_para(doc, "Bilimsel/Akademik Çıktılar", "Türkçe hukuk RAG için kaynak-temelli halüsinasyon değerlendirme yöntemi, etiketli/yarı-etiketli soru seti, karşılaştırmalı deney raporu ve hata taksonomisi. Nicel hedef: en az 1 açık veri seti sürümü + 1 teknik rapor + 1 poster/bildiri + 1 üniversite içi seminer.")
    add_kv_para(doc, "Açık Bilim / Tekrarlanabilirlik", "Değerlendirme seti ve deney betikleri proje sonunda GitHub + Zenodo üzerinden açık lisansla (veri CC BY 4.0, kod MIT) ve atıf alınabilir DOI ile KOŞULSUZ yayımlanacaktır. Hedeflenen sunum: ulusal bir bilişim/yapay zeka etkinliği (örn. UBMK/SİU) veya hukuk-bilişim çalıştayı.")
    add_kv_para(doc, "Toplumsal/Sosyal Çıktılar", "Hedef kitle hukuk fakültesi öğrencileri, baro/adli yardım birimleri ve Türkçe hukuk-NLP araştırmacılarıdır. Çıktı, alandaki diğer Türkçe hukuk YZ çalışmalarına referans/standart olabilecek, kaynak gösteren ve riskli cevabı reddeden sorumlu bir değerlendirme çerçevesidir.")
    add_kv_para(doc, "Araştırmacı Yetiştirme ve Yeni Projeler", "İnsan etiketli veri setinin büyütülmesi ve yeni hukuk alanlarına yayılımıyla 1002-A/2209-B başvurusu; bitirme tezi ve akademik yayın için temel.")

    add_budget(doc)

    add_section(doc, "6. BELİRTMEK İSTEDİĞİNİZ DİĞER KONULAR", level=1)
    add_block(doc, "", OTHER_TOPICS)
    add_references(doc)

    setup_footer(doc, "TÜBİTAK 2209-A Araştırma Önerisi")

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
