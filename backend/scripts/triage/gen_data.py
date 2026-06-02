"""DistilBERT-TR triaj sınıflandırıcısı için sentetik eğitim verisi üreteci.

8 sivil domain için (durum × soru) kombinasyonlarından çeşitli Türkçe hukuk
soruları üretir → data/triage/train.jsonl + val.jsonl ({"text","label"}).
Deterministik (seed=42). Gerçek kişi/TCKN YOK (repo kuralı — tamamen sentetik).

Kullanım:
    cd backend && uv run python -m scripts.triage.gen_data
    # → data/triage/train.jsonl, data/triage/val.jsonl
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from agents.triage_classifier import TRIAGE_LABELS

random.seed(42)

# Her domain için "durum" cümleleri (domain-spesifik, gerçekçi, sentetik).
SITUATIONS: dict[str, list[str]] = {
    "tuketici": [
        "İnternetten aldığım ürün ayıplı çıktı",
        "Mağazadan aldığım telefon iki gün sonra bozuldu",
        "Sipariş ettiğim ürün hâlâ elime ulaşmadı",
        "Garantili ürünüm arızalandı ama satıcı tamir etmiyor",
        "Online aldığım kıyafeti iade etmek istiyorum",
        "Aldığım hizmet sözleşmede belirtilenden farklı çıktı",
        "Mesafeli satışta cayma hakkımı kullanmak istiyorum",
        "Taksitli aldığım ürünü erken ödemek istiyorum",
        "Abonelik sözleşmemi iptal etmek istiyorum ama izin vermiyorlar",
        "Tüketici hakem heyetine başvurmak istiyorum",
        "Ayıplı malın bedel iadesini talep ediyorum",
        "Satıcı haksız bir şart dayattı",
    ],
    "isHukuku": [
        "İşten çıkarıldım ve kıdem tazminatımı alamadım",
        "Fazla mesai ücretlerim ödenmiyor",
        "İşveren ihbar tazminatı ödemeden beni çıkardı",
        "İşyerinde mobbinge maruz kalıyorum",
        "Maaşım iki aydır yatmıyor",
        "Doğum iznim sonrası işe iade edilmedim",
        "İş kazası geçirdim ve haklarımı öğrenmek istiyorum",
        "Deneme süresi içinde haksız yere çıkarıldım",
        "Yıllık iznimi kullandırmıyorlar",
        "Haklı nedenle işten ayrılmak istiyorum",
        "SGK primlerim eksik yatırılmış",
        "İşe iade davası açmak istiyorum",
    ],
    "kira": [
        "Ev sahibim depozitomu geri vermiyor",
        "Kira sözleşmem bitti ama ev sahibi tahliye istiyor",
        "Ev sahibi fahiş kira artışı talep ediyor",
        "Kiracı kirayı ödemiyor",
        "İşyeri kiramı ev sahibi haksız yere artırdı",
        "Konutu tahliye etmemi istiyorlar ama sözleşme devam ediyor",
        "Evi teslim ettim ama depozito iade edilmedi",
        "Ev sahibi gerekçe göstermeden tahliye istiyor",
        "Kira artış oranı yasal sınırı aşıyor",
        "Kiracım sözleşmeye aykırı davranıyor",
    ],
    "icra": [
        "Hakkımda icra takibi başlatıldı",
        "Maaşıma haciz geldi",
        "Ödeme emri tebliğ edildi ama borcu kabul etmiyorum",
        "Borca itiraz etmek istiyorum",
        "Alacağım için icra takibi başlatmak istiyorum",
        "Haczedilen eşyalarımı geri almak istiyorum",
        "İmzaya itiraz etmek istiyorum",
        "İlamsız takibe itiraz ettim ama alacaklı itirazın iptalini istiyor",
        "Senedimi ödemedi, kambiyo takibi yapacağım",
        "Maaş haczinin kaldırılmasını istiyorum",
    ],
    "trafik": [
        "Trafik kazası geçirdim ve karşı taraf kusurlu",
        "Aracımda değer kaybı oluştu",
        "Sigorta şirketi hasarımı ödemiyor",
        "Kasko aracımı pert ilan etti",
        "Trafik cezası yazıldı ama haksız olduğunu düşünüyorum",
        "Kaza sonrası zorunlu trafik sigortası ödeme yapmıyor",
        "Aracıma çarpan kişi kaçtı",
        "Değer kaybı tazminatı talep etmek istiyorum",
        "Hız ihlali cezasına itiraz etmek istiyorum",
        "Tespit tutanağına itirazım var",
    ],
    "vergi": [
        "Adıma haksız bir vergi cezası kesildi",
        "Vergi ziyaı cezası geldi",
        "KDV iadesi alamıyorum",
        "MTV borcumu taksitlendirmek istiyorum",
        "Gelir vergisi beyanımda hata yaptım, düzeltmek istiyorum",
        "Vergi dairesiyle uzlaşmak istiyorum",
        "Usulsüzlük cezasına itiraz edeceğim",
        "Gecikme faizi haksız hesaplanmış",
        "Tarhiyat öncesi uzlaşma talep ediyorum",
        "Pişmanlıkla beyanname vermek istiyorum",
    ],
    "tapu": [
        "Tapuda mülkiyet uyuşmazlığı yaşıyorum",
        "Kat mülkiyeti konusunda komşumla anlaşmazlığım var",
        "Arsamın imar durumu değişti",
        "Site yönetimi haksız aidat talep ediyor",
        "Tapuda muvazaalı bir devir olduğunu düşünüyorum",
        "Geçit hakkı için dava açmak istiyorum",
        "Ortaklığın giderilmesi davası açmak istiyorum",
        "Komşum benim arsama tecavüz etti",
        "İpotekli taşınmazımı satmak istiyorum",
        "Önalım (şufa) hakkımı kullanmak istiyorum",
    ],
    "idari": [
        "Belediyenin idari işlemine karşı iptal davası açmak istiyorum",
        "Kamulaştırma bedeli düşük belirlendi",
        "Ruhsat başvurum haksız yere reddedildi",
        "Hakkımda disiplin cezası verildi",
        "İdareye başvurdum ama zımni ret oldu",
        "İdari para cezasına itiraz etmek istiyorum",
        "Kamu görevlisiyim ve haksız bir işleme maruz kaldım",
        "Vatandaşlık başvurum reddedildi",
        "İdare mahkemesinde tam yargı davası açmak istiyorum",
        "Yürütmeyi durdurma talep etmek istiyorum",
    ],
}

# Genel "soru/ricalar" — durumla birleşip çeşitlilik üretir.
ASKS: list[str] = [
    "ne yapabilirim?",
    "hangi yasal yola başvurabilirim?",
    "haklarım nelerdir?",
    "nereye başvurmalıyım?",
    "dava açabilir miyim?",
    "nasıl bir süreç izlemem gerekiyor?",
    "yasal olarak ne talep edebilirim?",
    "bu konuda bana yardımcı olur musunuz?",
    "hukuki açıdan durumum nedir?",
    "ne kadar sürem var?",
    "",  # bazen durum tek başına (soru eki olmadan)
]


def _build(domain: str) -> list[str]:
    """Bir domain için (durum × soru) kombinasyonlarından benzersiz sorular."""
    out: set[str] = set()
    for sit in SITUATIONS[domain]:
        for ask in ASKS:
            q = f"{sit}, {ask}".strip().rstrip(",").strip() if ask else f"{sit}."
            out.add(q[0].upper() + q[1:])
    return sorted(out)


def main() -> None:
    rows: list[dict] = []
    for domain in TRIAGE_LABELS:
        for q in _build(domain):
            rows.append({"text": q, "label": domain})
    random.shuffle(rows)

    n_val = max(1, len(rows) // 10)
    val, train = rows[:n_val], rows[n_val:]
    out_dir = Path("data/triage")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("val", val)):
        path = out_dir / f"{name}.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in part) + "\n",
            encoding="utf-8",
        )
        print(f"  {name}: {len(part)} satır -> {path}")
    per = {d: sum(1 for r in rows if r["label"] == d) for d in TRIAGE_LABELS}
    print(f"  toplam: {len(rows)} | domain dağılımı: {per}")


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
