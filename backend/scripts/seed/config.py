"""Seed konfigürasyonu — frozen dataclass'lar ve merkezi sabitler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Bedesten API rate limit — 10 istek / 30 saniye / kaynak IP
BEDESTEN_CAPACITY = 10
BEDESTEN_REFILL_PER_SEC = 10.0 / 30.0

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
    """

    name: str
    keywords: tuple[str, ...]
    kanunlar: tuple[str, ...]
    applicable_courts: tuple[str, ...] = ALL_COURTS


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
        ),
        kanunlar=("TKHK",),
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
        ),
        kanunlar=("IK", "SGK"),
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
        ),
        kanunlar=("TBK",),
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
        ),
        kanunlar=("IIK",),
        applicable_courts=("yargitay", "anayasa"),  # Danıştay alakasız
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
        ),
        kanunlar=("KTK",),
        applicable_courts=ALL_COURTS,
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
        ),
        kanunlar=("VUK",),
        applicable_courts=ALL_COURTS,
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
        ),
        kanunlar=("TMK",),
        applicable_courts=ALL_COURTS,
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
        ),
        kanunlar=("IYUK", "DMK"),
        applicable_courts=("danistay", "anayasa"),  # Yargıtay alakasız
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
