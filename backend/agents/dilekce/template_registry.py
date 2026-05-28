"""Dilekçe template registry — domain × dilekçe türü eşlemesi + seçim mantığı.

8 domain × 2 dilekçe türü = 16 MVP template. Her template "<domain>/<type>.j2"
formatında diske kaydedilir; bu modül adların kanonik kaynağıdır.

Template seçimi:
    1. domain → adaylar (2-3 tür)
    2. case_facts anahtarları + soru içindeki keyword'lere göre puanla
    3. Eşit puanda alfabetik ilk (deterministic)
    4. Belirsizse: "generic" varsayılan (her domain için en kapsamlı tür)
"""

from __future__ import annotations

from agents.state import Domain

# Her domain için (qualified id, kısa ad, anahtar-kelime ipuçları) listesi.
# Anahtar kelimeler tr_lower'lı soru/olay/talep metninde aranır; eşleşme adedi
# puanı artırır. None değerli ipuçları → generic fallback.
TemplateMeta = tuple[str, str, tuple[str, ...]]

_REGISTRY: dict[Domain, tuple[TemplateMeta, ...]] = {
    "tuketici": (
        ("tuketici/hakem_heyeti_basvuru_v1", "Tüketici Hakem Heyeti Başvurusu",
         ("hakem heyeti", "şikayet", "değişim", "iade", "mağaza", "satıcı")),
        ("tuketici/ayipli_mal_iade_v1", "Ayıplı Mal İade/Bedel İndirimi Talebi",
         ("ayıplı", "bozuk", "şarj", "telefon", "buzdolabı", "garanti")),
    ),
    "isHukuku": (
        ("isHukuku/kidem_tazminat_talep_v1", "Kıdem Tazminatı Talep Dilekçesi",
         ("kıdem", "işten çıkarıldı", "tazminat", "yıl")),
        ("isHukuku/fazla_mesai_dava_v1", "Fazla Mesai Ücreti Dava Dilekçesi",
         ("fazla mesai", "mesai", "saat", "ödenmedi")),
    ),
    "kira": (
        ("kira/depozito_iade_v1", "Depozito İadesi Talep Dilekçesi",
         ("depozito", "iade", "ev sahibi", "vermek istemiyor")),
        ("kira/kira_tespit_dava_v1", "Kira Tespit Davası Dilekçesi",
         ("kira artışı", "tüfe", "zam", "tespit")),
    ),
    "icra": (
        ("icra/takip_itiraz_v1", "İcra Takibine İtiraz Dilekçesi",
         ("icra takibi", "itiraz", "ödeme emri")),
        ("icra/haciz_kaldirma_v1", "Maaş Haczinin Sınırlandırılması Dilekçesi",
         ("haciz", "maaş", "el konuldu")),
    ),
    "trafik": (
        ("trafik/trafik_cezasi_itiraz_v1", "Trafik İdari Para Cezasına İtiraz Dilekçesi",
         ("trafik cezası", "para cezası", "tutanak", "itiraz")),
        ("trafik/sigorta_tazminat_v1", "Sigorta Tazminat Talep Dilekçesi",
         ("sigorta", "tazminat", "kaza", "hasar")),
    ),
    "vergi": (
        ("vergi/vergi_ceza_itiraz_v1", "Vergi Cezasına İtiraz Dilekçesi",
         ("vergi cezası", "itiraz", "vuk", "ihbarname")),
        ("vergi/mtv_terkin_v1", "MTV Terkin / Gecikme Faizi Hesabı Dilekçesi",
         ("mtv", "motorlu taşıt", "gecikme")),
    ),
    "tapu": (
        ("tapu/mirascilik_belgesi_v1", "Mirasçılık Belgesi (Veraset İlamı) Talebi",
         ("miras", "veraset", "tapu", "intikal", "babam")),
        ("tapu/sinir_tecavuzu_v1", "El Atmanın Önlenmesi Dilekçesi",
         ("sınır", "tecavüz", "komşu", "müdahale", "bahçe")),
    ),
    "idari": (
        ("idari/iyu_dava_v1", "İdari İşlem İptal Dava Dilekçesi",
         ("iptal", "idari işlem", "iyu", "idare mahkemesi")),
        ("idari/kamulastirma_itiraz_v1", "Kamulaştırma Bedeline İtiraz Dilekçesi",
         ("kamulaştırma", "bedel", "itiraz")),
    ),
    "unknown": (),
}


def available_templates(domain: Domain) -> tuple[str, ...]:
    """Verilen domain için kayıtlı template id'leri (boş tuple olabilir)."""
    return tuple(meta[0] for meta in _REGISTRY.get(domain, ()))


def select_template_id(
    domain: Domain,
    soru: str,
    case_facts: dict[str, str] | None = None,
) -> str | None:
    """Domain + soru + olgulara göre en uygun template id'yi seç.

    Returns:
        Qualified template id (örn "tuketici/ayipli_mal_iade_v1") veya None
        (domain unknown ya da registry boş).

    Strateji: keyword eşleşme adetiyle puanla; en yüksek puan kazanır.
    Eşitlikte tuple sırası (registry'deki ilk). Hiç eşleşme yoksa ilk
    template (her domain için 'generic' anlamında ilk eklendi).
    """
    candidates = _REGISTRY.get(domain, ())
    if not candidates:
        return None
    haystack_parts = [soru.lower()]
    if case_facts:
        haystack_parts.extend(str(v).lower() for v in case_facts.values())
    haystack = " ".join(haystack_parts)

    best_id = candidates[0][0]
    best_score = -1
    for template_id, _label, keywords in candidates:
        score = sum(1 for kw in keywords if kw in haystack)
        if score > best_score:
            best_score = score
            best_id = template_id
    return best_id


def template_label(template_id: str) -> str:
    """Audit/UI için insan-okunabilir başlık."""
    for templates in _REGISTRY.values():
        for tid, label, _kws in templates:
            if tid == template_id:
                return label
    return template_id


__all__ = (
    "available_templates",
    "select_template_id",
    "template_label",
)
