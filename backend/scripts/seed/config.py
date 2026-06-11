"""Seed konfigürasyonu — frozen dataclass'lar ve merkezi sabitler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Bedesten API rate limit — Sprint-5 W13 fix: çok sıkı çıktı.
# Önceki: 10 burst + 1/3s refill (etkili ~17/30s) → 429 rate_limit_exceeded.
# Yeni: 3 burst + 1/5s refill (etkili ~6/30s, sustained 12/min).
# yargi-mcp 0.2.0 lokal bucket yanıtı 'retry_after: 3.5' → 5s konservatif.
BEDESTEN_CAPACITY = 3
BEDESTEN_REFILL_PER_SEC = 1.0 / 5.0

DEFAULT_BATCH_CHUNKS = 100
DEFAULT_LIMIT_PER_DOMAIN = 1000
DEFAULT_PROGRESS_EVERY = 50
DEFAULT_STATE_DIR = Path("data/seed_state")

# Tüm court'lar — default: bir domain tüm mahkemelerde aratılır
ALL_COURTS: tuple[str, ...] = ("yargitay", "danistay", "anayasa")


@dataclass(frozen=True, slots=True)
class DomainConfig:
    """Bir hukuk alanını arama keyword'leri + kanun kodları + court routing ile tanımlar.

    `applicable_courts`: bu domain HANGİ mahkemelerde aratılır?
    - Default: tüm court'lar (geri uyumluluk için mevcut domain'ler)
    - Özel routing: örn. "idari" Yargıtay'da boş döner → ("danistay", "anayasa")

    `chambers`: Sprint-5 W13 — opsiyonel daire filtresi.
    - Dict {court_id: (chamber1, chamber2, ...)}
    - Boş → tüm daireler aratılır (eski davranış)
    - Non-empty → her (keyword × chamber) ayrı API call → coverage artışı
    """

    name: str
    keywords: tuple[str, ...]
    kanunlar: tuple[str, ...]
    applicable_courts: tuple[str, ...] = ALL_COURTS
    # Sprint-5 W13: court_id → (chamber names) mapping
    # Bedesten API "birimAdi" parametresine direkt geçer.
    chambers: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True, slots=True)
class CourtConfig:
    """Bir mahkeme kaynağını tanımlar — sources.py'de gerçek implementasyon."""

    name: str
    display_name: str
    supports_chamber_filter: bool = True


DOMAINS: dict[str, DomainConfig] = {
    # === Mevcut 3 domain — tüm court'larda aratılır ===
    "tuketici": DomainConfig(
        name="tuketici",
        keywords=(
            "tüketici",
            "ayıplı mal",
            "ayıplı araç",
            "ayıplı konut",
            "garanti süresi",
            "iade hakkı",
            "tüketici hakem heyeti",
            "tüketici mahkemesi",
            "mesafeli satış",
            "kapıdan satış",
            "abonelik iptali",
            "haksız şart",
            "ön ödemeli konut",
            "devre tatil",
            "paket tur",
            "tüketici kredisi",
            "konut finansmanı",
            "ayıplı hizmet",
            # Sprint-5 W14: TKHK madde bazlı alt-kategoriler
            "TKHK 11 cayma hakkı",
            "TKHK 48 mesafeli cayma",
            "TKHK 49 kapıdan cayma",
            "TKHK 61 garanti belgesi",
            "TKHK 66 abonelik sözleşmesi",
            "TKHK 83 hakem heyeti karar",
            "TKHK 84 tüketici mahkemesi",
            "ayıp ihbarı süresi",
            "yenilemesiz iade",
        ),
        kanunlar=("TKHK",),
        # P9 (2026-06-11): chambers routing YOKTU → seed 11. HD (ticaret/sigorta)
        # hacmiyle doldu (tuketici-yargitay'ın %87'si 11. HD; gerçek tüketici
        # daireleri 3./13. HD + HGK 1/24 görünürlükteydi). Delta-seed bu filtreyle
        # doğru-daire chunk arzını artırır (iş/kira deseni).
        chambers={
            "yargitay": (
                "3. Hukuk Dairesi",
                "13. Hukuk Dairesi",
                "Hukuk Genel Kurulu",
            ),
        },
    ),
    "isHukuku": DomainConfig(
        name="isHukuku",
        keywords=(
            "kıdem tazminatı",
            "ihbar tazminatı",
            "haksız fesih",
            "işçi alacağı",
            "fazla mesai",
            "yıllık izin",
            "asgari ücret",
            "hafta tatili",
            "ulusal bayram",
            "iş kazası",
            "meslek hastalığı",
            "sendika hakkı",
            "toplu iş sözleşmesi",
            "mobbing",
            "iş güvencesi",
            "işe iade",
            "deneme süresi",
            "rekabet yasağı",
            "alt işveren",
            "muvazaa",
            # Sprint-5 W14: İK madde bazlı alt-kategoriler
            "İK 17 süreli fesih",
            "İK 24 işçi haklı sebep",
            "İK 25 işveren haklı sebep",
            "İK 41 fazla çalışma ücreti",
            "İK 55 yıllık izin hakkı",
            "SGK 4-1a sigortalılık",
            "SGK 86 emeklilik şartları",
            "iş sözleşmesi geçersizlik",
            "ücret bordrosu eksik",
        ),
        kanunlar=("IK", "SGK"),
        # Yargıtay 9. HD (iş hukuku genel), 22. HD (iş hukuku özel), 21. HD (iş kazası)
        chambers={
            "yargitay": (
                "9. Hukuk Dairesi",
                "22. Hukuk Dairesi",
                "21. Hukuk Dairesi",
            ),
        },
    ),
    "kira": DomainConfig(
        name="kira",
        keywords=(
            "kira sözleşmesi",
            "tahliye",
            "kira artışı",
            "kiracı",
            "konut kirası",
            "iş yeri kirası",
            "kefil",
            "depozito",
            "tahliye taahhüdü",
            "iki haklı ihtar",
            "kira tespit davası",
            "kira bedeli",
            "yenilenmiş kira",
            "kira artış oranı",
            "TÜFE oranı",
            "kira uyarlama",
            "kiraya veren",
            "kira borcu",
            "tahliye davası",
            # Sprint-5 W14: TBK madde bazlı alt-kategoriler
            "TBK 299 fesih bildirimi",
            "TBK 315 ihtarname kira",
            "TBK 339 kefil sorumluluğu",
            "TBK 344 artış sınırı",
            "TBK 347 sözleşme yenileme",
            "TBK 350 tahliye sebepleri",
            "TBK 351 kiraya veren ihtiyaç",
            "TBK 355 işyeri kirası",
            "kira sözleşmesi süre bitimi",
        ),
        kanunlar=("TBK",),
        # Yargıtay 3. HD (kira-alacak), 6. HD (kira sözleşme uyuşmazlığı)
        chambers={
            "yargitay": (
                "3. Hukuk Dairesi",
                "6. Hukuk Dairesi",
            ),
        },
    ),
    # === Yeni 5 domain — smart court routing (planner agent önerisi) ===
    "icra": DomainConfig(
        name="icra",
        keywords=(
            "icra takibi",
            "ilamsız takip",
            "ilamlı takip",
            "ödeme emri",
            "haciz",
            "haczin kaldırılması",
            "menfi tespit",
            "istirdat",
            "icra itirazı",
            "itirazın iptali",
            "itirazın kaldırılması",
            "borca itiraz",
            "imzaya itiraz",
            "icra mahkemesi",
            "iflas",
            "iflasın ertelenmesi",
            "konkordato",
            "tasarrufun iptali",
            "kambiyo senedi",
            "ihalenin feshi",
            # Sprint-5 W13 yeni keyword'ler
            "maaş haczi",
            "üçüncü kişi istihkak",
            "hisse haczi",
            "ihtiyati haciz",
            "icra emri",
            "borçlu temerrüdü",
        ),
        kanunlar=("IIK",),
        applicable_courts=("yargitay", "anayasa"),  # Danıştay alakasız
        # Sprint-5 W13: 12. HD primary (icra-iflas), 19. HD (kambiyo), 23. HD (iflas)
        chambers={
            "yargitay": (
                "12. Hukuk Dairesi",
                "19. Hukuk Dairesi",
                "23. Hukuk Dairesi",
            ),
        },
    ),
    "trafik": DomainConfig(
        name="trafik",
        keywords=(
            "trafik kazası",
            "maddi tazminat",
            "manevi tazminat",
            "destekten yoksun kalma",
            "maluliyet",
            "iş göremezlik",
            "kusur oranı",
            "zorunlu mali sorumluluk sigortası",
            "kasko sigortası",
            "trafik sigortası",
            "sigorta tahkim komisyonu",
            "değer kaybı",
            "araç değer kaybı",
            "alkollü araç kullanma",
            "hatır taşıması",
            "rücu davası",
            "karayolları trafik kanunu",
            "ölümlü trafik kazası",
            "yaralamalı trafik kazası",
            # Sprint-5 W13 yeni keyword'ler
            "ZMSS poliçesi",
            "sürücü belgesi iptali",
            "tutanak süresi",
            "trafik para cezası",
            "ağır kusur",
            "sigorta limiti",
        ),
        kanunlar=("KTK",),
        applicable_courts=ALL_COURTS,
        # Sprint-5 W13: 17. HD primary (trafik tazminatı), 4. HD (sigorta tahkim)
        chambers={
            "yargitay": (
                "17. Hukuk Dairesi",
                "4. Hukuk Dairesi",
            ),
            "danistay": (
                "12. Daire",  # Sürücü belgesi iptali
            ),
        },
    ),
    "vergi": DomainConfig(
        name="vergi",
        keywords=(
            "vergi ziyaı",
            "vergi ziyaı cezası",
            "özel usulsüzlük cezası",
            "vergi inceleme raporu",
            "vergi tekniği raporu",
            "ihtirazi kayıt",
            "tarhiyat",
            "re'sen tarh",
            "ikmalen tarhiyat",
            "uzlaşma",
            "vergi mahkemesi",
            "katma değer vergisi",
            "kurumlar vergisi",
            "gelir vergisi",
            "sahte fatura",
            "naylon fatura",
            "mücbir sebep",
            "düzeltme şikayet",
            "haksız iade",
            # Sprint-5 W13 yeni keyword'ler
            "özel tüketim vergisi",
            "damga vergisi",
            "motorlu taşıt vergisi",
            "emlak vergisi",
            "amme alacağı",
            "vergi ceza ihbarnamesi",
        ),
        kanunlar=("VUK",),
        applicable_courts=ALL_COURTS,
        # Sprint-5 W13: Danıştay 4. D (gelir), 7. D (gümrük), 9. D (vergi davaları)
        chambers={
            "danistay": (
                "4. Daire",
                "7. Daire",
                "9. Daire",
            ),
        },
    ),
    "tapu": DomainConfig(
        name="tapu",
        keywords=(
            "tapu iptali",
            "tapu tescili",
            "tapu kaydı",
            "tapu sicili",
            "men-i müdahale",
            "müdahalenin men'i",
            "ecrimisil",
            "kat mülkiyeti",
            "müşterek mülkiyet",
            "paylı mülkiyet",
            "elbirliği mülkiyeti",
            "intifa hakkı",
            "ipotek",
            "şufa hakkı",
            "önalım hakkı",
            "muris muvazaası",
            "kadastro tespiti",
            "zilyetlik",
            "taşınmaz mülkiyeti",
            "tapu iptali ve tescili",
            "izale-i şuyu",
            "ortaklığın giderilmesi",
            # Sprint-5 W13 yeni keyword'ler
            "kamulaştırma bedeli",
            "kamulaştırmasız el atma",
            "imar planı iptali",
            "ifraz tevhid",
            "ruhsatsız yapı",
            "kentsel dönüşüm",
        ),
        kanunlar=("TMK",),
        applicable_courts=ALL_COURTS,
        # Sprint-5 W13: 1. HD (tapu iptali), 8. HD (izale-i şuyu), 14. HD (kadastro)
        chambers={
            "yargitay": (
                "1. Hukuk Dairesi",
                "8. Hukuk Dairesi",
                "14. Hukuk Dairesi",
            ),
            "danistay": (
                "6. Daire",  # Kamulaştırma
            ),
        },
    ),
    "idari": DomainConfig(
        name="idari",
        keywords=(
            "iptal davası",
            "tam yargı davası",
            "idari işlem",
            "idari para cezası",
            "disiplin cezası",
            "memur disiplin",
            "kamulaştırma",
            "kamulaştırmasız el atma",
            "imar planı",
            "ruhsat iptali",
            "ihale iptali",
            "kamu ihalesi",
            "yürütmenin durdurulması",
            "hizmet kusuru",
            "idari yargı",
            "atama işlemi",
            "naklen atama",
            "göreve iade",
            "657 sayılı kanun",
            "devlet memuru",
            "idarenin sorumluluğu",
            # Sprint-5 W13 yeni keyword'ler
            "ihaleden yasaklanma",
            "ihale uhdesinde kalma",
            "memur soruşturması",
            "çevre para cezası",
            "belediye meclis kararı",
            "yapı tatil tutanağı",
        ),
        kanunlar=("IYUK", "DMK"),
        applicable_courts=("danistay", "anayasa"),  # Yargıtay alakasız
        # Sprint-5 W13: Danıştay 5. D (memur), 6. D (imar), 10. D (genel idare),
        # 12. D (sürücü, eğitim), 13. D (ihale)
        chambers={
            "danistay": (
                "5. Daire",
                "6. Daire",
                "10. Daire",
                "12. Daire",
                "13. Daire",
            ),
        },
    ),
}


COURTS: dict[str, CourtConfig] = {
    "yargitay": CourtConfig(name="yargitay", display_name="Yargıtay"),
    "danistay": CourtConfig(name="danistay", display_name="Danıştay"),
    "anayasa": CourtConfig(
        name="anayasa",
        display_name="Anayasa Mahkemesi",
        supports_chamber_filter=False,
    ),
}


@dataclass(frozen=True, slots=True)
class SeedConfig:
    """Bir seed çalışmasının tüm parametreleri."""

    domains: Sequence[str]
    courts: Sequence[str]
    limit_per_domain: int = DEFAULT_LIMIT_PER_DOMAIN
    batch_chunks: int = DEFAULT_BATCH_CHUNKS
    progress_every: int = DEFAULT_PROGRESS_EVERY
    resume: bool = True
    dry_run: bool = False
    state_dir: Path = DEFAULT_STATE_DIR

    def iter_court_domain_matrix(self) -> list[tuple[CourtConfig, DomainConfig]]:
        """(court, domain) çiftlerini üret — domain'in applicable_courts'ı filtrelenir.

        Örn: --court all --domain idari → idari ("danistay", "anayasa") olduğu için
        yargıtay/idari çifti atlanır.
        """
        pairs: list[tuple[CourtConfig, DomainConfig]] = []
        for court_name in self.courts:
            court = COURTS[court_name]
            for domain_name in self.domains:
                domain = DOMAINS[domain_name]
                if court_name not in domain.applicable_courts:
                    continue
                pairs.append((court, domain))
        return pairs
