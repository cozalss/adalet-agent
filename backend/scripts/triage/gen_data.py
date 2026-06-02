"""DistilBERT-TR triaj sınıflandırıcısı için sentetik eğitim verisi üreteci.

8 sivil domain için SLOT-tabanlı durum şablonları × çeşitli soru kalıplarından
zengin, gerçekçi Türkçe hukuk soruları üretir → data/triage/{train,val}.jsonl.
Slot varyasyonu (ürün/taraf/süre vb.) model genelleme GÜVENİNİ yükseltir: gerçek
ifadeler şablona birebir benzemese de domain doğru + emin sınıflandırılır.

Deterministik (seed=42). Gerçek kişi/TCKN YOK (tamamen sentetik — repo kuralı).

Kullanım: cd backend && uv run python -m scripts.triage.gen_data
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from agents.triage_classifier import TRIAGE_LABELS

random.seed(42)

# Slot kelime havuzları — durum şablonlarına doldurulup kelime çeşitliliği yaratır.
SLOTS: dict[str, list[str]] = {
    "urun": ["telefon", "buzdolabı", "çamaşır makinesi", "ayakkabı", "koltuk takımı",
             "bilgisayar", "televizyon", "kol saati", "klima", "bulaşık makinesi",
             "spor ayakkabı", "cep telefonu", "tablet", "fırın"],
    "sure": ["6 ay", "1 yıl", "2 yıl", "3 yıl", "5 yıl", "8 ay", "10 ay", "4 yıl"],
    "tutar": ["5.000 TL", "12.000 TL", "20.000 TL", "35.000 TL", "50.000 TL", "8.500 TL"],
    "kurum": ["belediye", "valilik", "kaymakamlık", "il müdürlüğü", "bakanlık"],
}


def _fill(template: str) -> list[str]:
    """Şablondaki {slot}'ları havuzdan örnekle (slot başına 3 varyant)."""
    import re

    slots = re.findall(r"\{(\w+)\}", template)
    if not slots:
        return [template]
    out: list[str] = []
    for _ in range(3):
        filled = template
        for s in slots:
            filled = filled.replace("{" + s + "}", random.choice(SLOTS[s]), 1)
        out.append(filled)
    return out


# Domain durum şablonları (slot'lu + slot'suz, çeşitli ifade biçimleri).
SITUATIONS: dict[str, list[str]] = {
    "tuketici": [
        "İnternetten aldığım {urun} ayıplı çıktı", "Mağazadan aldığım {urun} bozuldu",
        "Sipariş ettiğim {urun} hâlâ elime ulaşmadı", "{urun} garantili olmasına rağmen tamir edilmiyor",
        "Online aldığım {urun} bedenini iade etmek istiyorum", "Aldığım {urun} reklamdakinden farklı çıktı",
        "Mesafeli satışta {urun} için cayma hakkımı kullanmak istiyorum",
        "Taksitle aldığım {urun} borcunu erken kapatmak istiyorum", "Satıcı {urun} değişimini reddediyor",
        "Aboneliğimi iptal etmek istiyorum ama izin vermiyorlar", "Tüketici hakem heyetine başvuracağım",
        "Aldığım hizmet sözleşmede yazandan kötü çıktı", "İade ettiğim {urun} parasını geri vermiyorlar",
        "Satıcı haksız bir sözleşme şartı dayattı", "Kredi kartıyla aldığım {urun} hiç gelmedi",
    ],
    "isHukuku": [
        "{sure} çalıştığım işten çıkarıldım kıdem tazminatımı alamadım",
        "Fazla mesai ücretlerim ödenmiyor", "İşveren ihbar tazminatı ödemeden beni kovdu",
        "İş yerinde mobbinge ve baskıya maruz kalıyorum", "Maaşım {sure} dır yatmıyor",
        "Doğum izni sonrası işe geri alınmadım", "İş kazası geçirdim haklarımı bilmiyorum",
        "Deneme süresinde haksız yere kovuldum", "Yıllık iznimi kullandırmıyorlar",
        "Haklı sebeple istifa etmek istiyorum", "SGK primlerim eksik gösterilmiş",
        "İşe iade davası açmak istiyorum", "Patronum sebep göstermeden beni çıkardı",
        "Asgari ücretin altında çalıştırılıyorum", "İşten ayrıldım ama hakkımı vermediler",
    ],
    "kira": [
        "Ev sahibim {tutar} depozitomu geri vermiyor", "Kira sözleşmem bitti ama ev sahibi çıkmamı istiyor",
        "Ev sahibi fahiş kira zammı talep ediyor", "Kiracım kirayı ödemiyor",
        "İş yeri kiramı haksız yere artırdılar", "Sözleşme sürerken tahliye istiyorlar",
        "Evi boşalttım ama depozitomu iade etmediler", "Ev sahibi gerekçesiz tahliye istiyor",
        "Kira artış oranı yasal sınırı aşıyor", "Kiracım eve zarar verdi",
        "Komşu kiracı sürekli gürültü yapıyor", "Ev sahibim sözleşmeyi tek taraflı feshetti",
        "Depozito iadesi için ne yapmalıyım", "Kira kontratım yenilenmiyor",
    ],
    "icra": [
        "Hakkımda icra takibi başlatıldı", "Maaşıma haciz kondu",
        "Bana ödeme emri geldi ama borcu kabul etmiyorum", "Borca itiraz etmek istiyorum",
        "Alacağım için icra takibi başlatacağım", "Haczedilen eşyalarımı geri almak istiyorum",
        "Senet imzama itiraz ediyorum", "İlamsız takibe itiraz ettim alacaklı iptalini istiyor",
        "Karşılıksız çek için takip yapacağım", "Maaş haczinin kaldırılmasını istiyorum",
        "İcra dosyam kapanmadı borcu ödedim", "Evime haciz için geldiler",
        "Kefil olduğum borç için takip başladı", "Banka kredisini ödeyemedim icra geldi",
    ],
    "trafik": [
        "Trafik kazasında karşı taraf kusurlu", "Aracımda kaza sonrası değer kaybı oluştu",
        "Sigorta şirketi hasar bedelini ödemiyor", "Kaskom aracımı pert ilan etti",
        "Haksız yazıldığını düşündüğüm trafik cezası aldım", "Zorunlu trafik sigortası ödeme yapmıyor",
        "Aracıma çarpan sürücü kaçtı", "Değer kaybı tazminatı talep edeceğim",
        "Hız cezasına itiraz etmek istiyorum", "Kaza tespit tutanağına itirazım var",
        "Çekiciye alınan aracım için ceza yazıldı", "Maddi hasarlı kazada anlaşamadık",
        "Ehliyetime el konuldu", "Park hâlindeki aracıma çarptılar",
    ],
    "vergi": [
        "Adıma haksız {tutar} vergi cezası kesildi", "Vergi ziyaı cezası geldi",
        "KDV iademi alamıyorum", "Motorlu taşıtlar vergisini taksitlendirmek istiyorum",
        "Gelir vergisi beyanımda hata yaptım düzeltmek istiyorum", "Vergi dairesiyle uzlaşmak istiyorum",
        "Usulsüzlük cezasına itiraz edeceğim", "Gecikme faizi haksız hesaplanmış",
        "Tarhiyat öncesi uzlaşma talep ediyorum", "Pişmanlıkla beyanname vermek istiyorum",
        "Emlak vergim yanlış hesaplanmış", "Vergi borcumu yapılandırmak istiyorum",
        "Mükellefiyetim haksız açıldı", "Vergi incelemesi başlatıldı ne yapmalıyım",
    ],
    "tapu": [
        "Tapuda mülkiyet uyuşmazlığım var", "Kat mülkiyetinde komşumla anlaşamıyorum",
        "Arsamın imar durumu değişti", "Site yönetimi haksız aidat istiyor",
        "Tapuda muvazaalı devir olduğunu düşünüyorum", "Geçit hakkı için dava açacağım",
        "Ortaklığın giderilmesi davası açmak istiyorum", "Komşum arsama tecavüz etti",
        "İpotekli evimi satmak istiyorum", "Önalım hakkımı kullanmak istiyorum",
        "Apartmanda ortak alan sorunu yaşıyorum", "Miras kalan tarlayı paylaşamıyoruz",
        "Tapu kaydında hata var düzelttirmek istiyorum", "Kaçak yapı yüzünden ceza geldi",
    ],
    "idari": [
        "{kurum} işlemine karşı iptal davası açacağım", "Kamulaştırma bedeli çok düşük belirlendi",
        "Ruhsat başvurum haksız reddedildi", "Hakkımda disiplin cezası verildi",
        "{kurum} a başvurdum ama cevap vermedi zımni ret oldu", "İdari para cezasına itiraz edeceğim",
        "Kamu görevlisiyim haksız bir işleme maruz kaldım", "Vatandaşlık başvurum reddedildi",
        "İdare mahkemesinde tam yargı davası açmak istiyorum", "Yürütmeyi durdurma talep edeceğim",
        "{kurum} bana izin vermiyor", "Memuriyetten haksız ihraç edildim",
        "İmar planına itiraz etmek istiyorum", "Atama kararım iptal edildi",
    ],
}

# Çeşitli soru/rica ekleri (durumla birleşir).
ASKS: list[str] = [
    "ne yapabilirim", "hangi yasal yola başvurabilirim", "haklarım nelerdir",
    "nereye başvurmalıyım", "dava açabilir miyim", "nasıl bir süreç izlemeliyim",
    "yasal olarak ne talep edebilirim", "bana yardımcı olur musunuz",
    "hukuki açıdan durumum nedir", "ne kadar sürem var", "tazminat alabilir miyim",
    "",
]


def _build(domain: str) -> list[str]:
    """Bir domain için (slot-doldurulmuş durum × soru) benzersiz sorular."""
    out: set[str] = set()
    for tmpl in SITUATIONS[domain]:
        for sit in _fill(tmpl):
            for ask in ASKS:
                q = f"{sit}, {ask}?" if ask else f"{sit}."
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
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in part) + "\n",
                        encoding="utf-8")
        print(f"  {name}: {len(part)} satır -> {path}")
    per = {d: sum(1 for r in rows if r["label"] == d) for d in TRIAGE_LABELS}
    print(f"  toplam: {len(rows)} | domain dağılımı: {per}")


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
