"""Ajan zinciri sabitleri — tek yerden değişsin."""

from __future__ import annotations

import os

# --- Döngü kontrolü ---
MAX_RETRY = 3                    # debate → draft re-loop max
MIN_DOMAIN_CONFIDENCE = 0.35     # bu altına düşerse "netleştirin" reddi

# --- Retrieval limitleri ---
TOP_K_LAW = 8                    # Mevzuat ajanı top-k madde
TOP_K_CASE = 8                   # Emsal ajanı top-k karar
RERANK_CANDIDATES = 30           # Cross-encoder'a giren aday sayısı

# --- Verifier eşikleri ---
# Not (Sprint-7/8 sonu): Gerçek Qwen 14B Q4 ile yapılan E2E ölçümlerde
# çok katı eşikler (0.72/0.50) Türkçe paraphrase'lerde aşırı reject üretti
# (5/8 reject). Eşikleri makul seviyeye çektik — verify hâlâ yalan iddia
# (contradiction) ve sıfır-destek vakalarını yakalar ama gerçek paraphrase'i
# reddetmez. Cifte sigorta: debate ayrıca constitutional self-critique yapar.
NLI_ENTAILMENT_THRESHOLD = float(os.getenv("NLI_ENTAILMENT_THRESHOLD", "0.55"))
# Sprint-4 W4.5: env-override için. A/B test: 0.65 / 0.70 / 0.75 üçü için
# freeze_baseline koşulabilir → eval/runs/v2_nli_<th>_<sha>.json karşılaştır.
NLI_CONTRADICTION_THRESHOLD = float(os.getenv("NLI_CONTRADICTION_THRESHOLD", "0.70"))
# v7 ölçümü (E1/E2/E3 regresyon): 16 kanun seed sonrası retrieval daha
# çeşitlendi, NLI bazı paraphrase'leri 0.50-0.70 contradiction skoru ile
# yanlış-pozitif veto yaptı (Türkçe XNLI hassasiyeti). 0.70 ile sadece açık
# çelişkileri yakalar; gerçek halüsinasyon koruması fuzzy + LLM-as-judge'a
# kayar. [[adalet_nli_finding]] memory ile uyumlu.
FUZZY_SUPPORT_THRESHOLD = 0.55   # fuzzy >= bu = pozitif destek (0.72→0.60→0.55)
LETTUCE_SUPPORT_THRESHOLD = 0.45 # LettuceDetect token-grounding (0.55→0.45)
LETTUCE_VETO_THRESHOLD = 0.15    # LettuceDetect < bu = veto (0.20→0.15)
MIN_VERIFIED_CLAIMS_RATIO = 0.20 # taslakta kanıtlanan claim oranı (0.50→0.30→0.20)
# v8 ölçümü: 16 kanun ile retrieval çeşitlendi, fuzzy match kaynak bulamadı
# (claim'ler birden çok kanunla potansiyel ilişkili, snippet seçimi rastgele).
# 0.20 = 5 claim'den 1+ supported yeterli; halüsinasyon koruması NLI 0.70 +
# fuzzy 0.55 + LettuceDetect kombosuyla yapılıyor.
VERIFY_BATCH = 16                # NLI batch boyutu (GPU/CPU)


def is_verify_strict() -> bool:
    """Fail-closed doğrulama modu (production hardening).

    `VERIFY_STRICT=1`: NLI veya LettuceDetect doğrulayıcısı yüklü OLMASI
    beklenirken bir EXCEPTION fırlatırsa (model yüklenemedi / inference çöktü),
    sessizce pas geçmek YERİNE cevabı reddet. Doğrulayıcı çalışmadıysa iddiayı
    "doğrulanmış" sayamayız — SIFIR HALÜSİNASYON garantisi (CLAUDE.md §1).

    Default `0`: dev/test/mock ortamı. Bu ortamlarda NLI/Lettuce modelleri
    KASITLI olarak yok; o yüzden graceful degrade (mevcut davranış) korunur.

    Dinamik okunur (import-time sabit değil) ki testler `monkeypatch.setenv`
    ile per-test toggle edebilsin; graph.py'deki CRAG/Self-RAG bayrak desenine
    uyumlu.
    """
    return os.getenv("VERIFY_STRICT", "0").lower() in {"1", "true", "yes"}

# --- Debate ---
DEBATE_REJECT_THRESHOLD = 0.30   # critique score < bu = hard reject
MAX_DEBATE_LOOPS = 2             # constitutional self-critique iter max

# --- LLM ---
LLM_MAX_TOKENS = 1536            # draft cevabı için
LLM_TEMPERATURE = 0.1            # hukuki üretim — düşük sıcaklık şart
LLM_CONTEXT_BUDGET = 3000        # context'in retrieval'a ayrılan token oranı
# Not: 12-kanun seed sonrası retrieval blok büyüdü (8 law + 8 case × 600 char
# = ~10KB ≈ 2500 token). System+soru+template ile 4096 token llama-server -c
# default'unu aşıyordu (400 Bad Request). 3000'e düşürdük; 8 ref × ~1500 char
# ≈ 3000 token + 1000 sistem/template = 4000 → güvenli sınır içinde.

# --- HyDE & Multi-Query ---
HYDE_ENABLED = os.getenv("HYDE_ENABLED", "1") not in {"0", "false", "False"}
# Sprint-4 W1: 2.0s → 15.0s. v1_hyde_ab0773c.json ölçümünde Qwen 14B Q4 -ngl 20
# partial-offload ile 200 token üretim ortalama 14-17s; 2s default tüm 50 vakayı
# silent timeout'a düşürüp HyDE'ı pratik olarak hybrid'e degrade etti. ENV ile
# override edilebilir (hızlı LLM'lerde 5s yeterli). Ek 25s buffer (Qdrant+embed)
# mevzuat_node.timeout_total üzerinde toplam ~40s — production p95 limiti.
HYDE_TIMEOUT_S = float(os.getenv("HYDE_TIMEOUT_S", "15.0"))
HYDE_MAX_TOKENS = 200
MULTI_QUERY_ENABLED = os.getenv("MULTI_QUERY_ENABLED", "1") not in {"0", "false", "False"}
# Sprint-4 W1: 4 → 5. Literatürde N=5-8 standard, paraphrase çeşitliliği +Recall@20.
# Cache hit'lerde maliyetsiz. Per-paraphrase 1.5s + RRF merge yeterli.
MULTI_QUERY_N = int(os.getenv("MULTI_QUERY_N", "5"))

# --- Sprint-7/8 (Tier-3) opsiyonel SOTA toggle'ları ---
# Default OFF: ENV=1 ile etkin. Bayrak kapalıyken graph topolojisi Sprint-3 ile aynı.
SELF_RAG_ENABLED = False         # reflection tokens — debate sonrası ek katman
CRAG_ENABLED = False             # retrieval confidence düşükse correction
RAPTOR_ENABLED = False           # hiyerarşik özet ağacı (offline build)
GRAPH_RAG_ENABLED = False        # bilgi grafı (offline build + online expand)

# Self-RAG eşikleri
SELF_RAG_UTILITY_MIN = 3         # utility < bu = retry sinyali
MAX_REFLECT = 2                  # self-RAG reflection iter max

# CRAG eşikleri
CRAG_CONFIDENCE_THRESHOLD = 0.35 # top-1 retrieval score < bu = correction
CRAG_MIN_REFS = 3                # toplam ref < bu = correction
CRAG_TOP_K = 5                   # correction multi-query top-k

# --- Sprint-4 W1: Pre-domain filter (mevzuat post-retrieve boost) ---
# Triaj'dan gelen domain'i mevzuat sonuçlarına filter olarak uygula.
# Mevzuat seed'lerde domain field yok (re-seed pahalı) — payload'daki
# `kanun_kodu` üzerinden domain ↔ kanun haritasıyla yumuşak re-rank yapılır.
MEVZUAT_DOMAIN_FILTER_ENABLED = (
    os.getenv("MEVZUAT_DOMAIN_FILTER", "1").lower() in {"1", "true", "yes"}
)

# Domain → kanun_kodu (mevzuat seed'in payload'a yazdığı alfabetik kod).
# Sprint-5 W12: Her domain için 5+ ilgili kanun.
# Sprint-5 fix: payload'da `kanun_kodu` ALFABETİK (TKHK, TBK, TTK),
# `kanun_numarasi` numerik (6502, 6098, 6102). mevzuat_node._boost_by_domain
# kanun_kodu field'ına baktığı için mapping ALFABETİK olmalı — yoksa boost
# hiç eşleşmez (Sprint-4 pre-existing bug).
DOMAIN_TO_KANUN_KODU: dict[str, tuple[str, ...]] = {
    "tuketici":  (
        "TKHK",     # 6502 — Tüketici
        "TBK",      # 6098 — Borçlar (sözleşme)
        "TTK",      # 6102 — Ticaret (e-ticaret)
        "BK",       # 5411 — Bankacılık
        "SIGORTA",  # 5684 — Sigortacılık
        "KVKK",     # 6698 — Veri koruma
        "RKHK",     # 4054 — Rekabet
        "OHK",      # 6493 — Ödeme Hizmetleri
    ),
    "isHukuku":  (
        "IK",       # 4857 — İş
        "SGK",      # 5510 — Sosyal Sigorta
        "SK",       # 6356 — Sendikalar
        "ISGK",     # 6331 — İş Sağlığı Güvenliği
        "DMK",      # 657 — Devlet Memurları
        "TBK",      # 6098 — Borçlar (hizmet sözleşmesi)
        "DIK",      # 854 — Deniz İş
        "BMC",      # 5953 — Basın Mesleği
        "OGK",      # 5188 — Özel Güvenlik
    ),
    "kira":      (
        "TBK",      # 6098 — Borçlar (kira bölümü)
        "TMK",      # 4721 — Medeni (mülkiyet)
        "KMK",      # 634 — Kat Mülkiyeti
        "KDK",      # 6306 — Kentsel Dönüşüm
        "BLDK",     # 5393 — Belediye
    ),
    "icra":      (
        "IIK",      # 2004 — İcra İflas
        "TTK",      # 6102 — Kambiyo senetleri
        "AATUHK",   # 6183 — Amme Alacağı
        "BK",       # 5411 — Banka kredisi
        "SGK",      # 5510 — SGK alacağı
    ),
    "trafik":    (
        "KTK",      # 2918 — Karayolları Trafik
        "SIGORTA",  # 5684 — Sigortacılık (ZMSS)
        "TBK",      # 6098 — Borçlar (haksız fiil)
        "SGK",      # 5510 — Kaza tazminat
        "KGK",      # 4925 — Karayolu Taşıma
    ),
    "vergi":     (
        "VUK",      # 213 — Vergi Usul
        "GVK",      # 193 — Gelir Vergisi
        "KVK",      # 5520 — Kurumlar Vergisi
        "KDV",      # 3065 — Katma Değer
        "OTV",      # 4760 — Özel Tüketim
        "DV",       # 488 — Damga
        "MTV",      # 197 — Motorlu Taşıt
        "EMLAKV",   # 1319 — Emlak
        "AATUHK",   # 6183 — Amme Alacağı
        "MYK",      # 5018 — Mali Yönetim
    ),
    "tapu":      (
        "TMK",      # 4721 — Medeni
        "TPK",      # 2644 — Tapu
        "KMK",      # 634 — Kat Mülkiyeti
        "IMARK",    # 3194 — İmar
        "KAMK",     # 2942 — Kamulaştırma
        "KDK",      # 6306 — Kentsel Dönüşüm
    ),
    "idari":     (
        "IYUK",     # 2577 — İdari Yargılama
        "DMK",      # 657 — Devlet Memurları
        "MYK",      # 5018 — Mali Yönetim
        "IHK",      # 4734 — Kamu İhale
        "IHSK",     # 4735 — İhale Sözleşmeleri
        "DIHK",     # 3071 — Dilekçe Hakkı
        "BLDK",     # 5393 — Belediye
        "IOIK",     # 5302 — İl Özel
        "CK",       # 2872 — Çevre
    ),
}

# Düzenleyici otorite → ilgili domain'ler (Sprint-5 W15)
# Bu mapping regulator karar'larını domain'lere yönlendirir (retrieval filter).
# Sprint-5 W15: local yargi-mcp tools'la entegre — bddk + sigorta_tahkim
# upstream broken (Tavily 433), spk listede ama public API yok.
REGULATOR_TO_DOMAINS: dict[str, tuple[str, ...]] = {
    "kvkk":           ("tuketici", "isHukuku"),  # Kişisel veri
    "rekabet":        ("tuketici",),              # Rekabet ihlali / antitrust
    "sayistay":       ("idari", "vergi"),         # Kamu mali denetim
    "gib_ozelge":     ("vergi",),                 # Gelir İdaresi özelge — vergi yorumları
    "sigorta_tahkim": ("trafik", "tuketici"),     # Sigorta tahkim — trafik/sağlık/kasko (currently broken upstream)
    "bddk":           ("tuketici",),              # Banka tüketicisi (currently broken upstream)
    "spk":            ("tuketici",),              # Yatırımcı/finansal tüketici (no public API)
}

# Domain'e uyan sonuçların skor boost'u — RRF/dense score üstüne ek (top'a it).
MEVZUAT_DOMAIN_BOOST = float(os.getenv("MEVZUAT_DOMAIN_BOOST", "0.15"))

# --- Disclaimer ---
DISCLAIMER_TR = (
    "⚠️ Bu cevap hukuki tavsiye değildir, sadece bilgilendirme amaçlıdır. "
    "Karmaşık veya kritik durumlarda lütfen bir avukata danışın."
)

REJECT_TEMPLATE_TR = (
    "Bu soruya doğrulanmış kaynaklarla yanıt veremedim. "
    "Lütfen bir avukata danışın."
)

# --- Kapsam dışı ---
# CLAUDE.md §4 kapsam: tuketici, isHukuku, kira, icra, trafik, vergi, tapu, idari.
# Ceza ve aile hukuku açıkça dışarıda. Ancak "vergi cezası", "trafik cezası" gibi
# kombinasyonlar yasal terimlerdir → "ceza" tek-token kontrolü değil, net çok-token
# veya açık ceza-hukuku göstergeleri ile match yap.
OUT_OF_SCOPE_KEYWORDS = (
    # Ceza hukuku — çok-token form'lar
    "ceza hukuku", "ceza davası", "ceza yargılaması", "ceza muhakemesi",
    "ağır ceza", "asliye ceza", "ceza mahkemesi",
    "cinayet", "öldürme", "tcm m.81", "kasten öldürme",
    "suç işle", "suç eylem",  # "suç" tek tanesi false-positive üretiyordu
    "tutuklama", "tutuklu", "gözaltı",
    # Aile hukuku — çok-token form'lar
    "boşanma davası", "nafaka", "velayet", "evlat edinme",
    "aile hukuku", "aile mahkemesi",
)
