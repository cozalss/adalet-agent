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
FUZZY_SUPPORT_THRESHOLD = 0.45   # fuzzy >= bu = pozitif destek (0.72→0.60→0.55→0.45)
# verify_calibration.py çıktısı (59-vakalı altın veri seti, 2026-05-30):
#   th=0.45 → F1=0.73 Acc=0.71 (TP=23 FP=15 TN=19 FN=2)
#   th=0.55 → F1=0.53 Acc=0.61 (TP=13 FP=11 TN=23 FN=12)  ← eski değer
# 0.45 ile 10 gerçek-pozitif kazanılır (+recall), 4 yanlış-pozitif artar;
# ek FP'ler NLI contradiction veto (0.70) + Lettuce veto (0.15) tarafından yakalanır.
LETTUCE_SUPPORT_THRESHOLD = 0.45 # LettuceDetect token-grounding (0.55→0.45)
LETTUCE_VETO_THRESHOLD = 0.15    # LettuceDetect < bu = veto (0.20→0.15)
MIN_VERIFIED_CLAIMS_RATIO = 0.20 # taslakta kanıtlanan claim oranı (0.50→0.30→0.20)
# Kalibrasyon notu: model-free pipeline (L1+fuzzy) contradiction'da acc=0.23 —
# NLI zorunlu (VERIFY_STRICT=1 production'da açık olmalı). Lettuce contradiction
# gap=0.21 (fuzzy'den daha iyi), ek layer olarak değer taşır.
VERIFY_BATCH = 16                # NLI batch boyutu (GPU/CPU)

# --- NLI doğrulama cache ---
# NLI deterministik (model.eval() + temp=0): aynı (claim_text, evidence_snippet)
# her zaman aynı raw skoru üretir → cache'lenebilir. NLI ~100ms/pair GPU; cache hit
# Redis ~1ms / mem ~0. RAW skor cache'lenir (eşik OKUMA anında uygulanır) → eşik
# değişse cache geçerli kalır. Key namespace NLI model adına bağlı (model değişimi
# cache'i otomatik invalidate eder). Redis yoksa process-local bounded dict'e düşer.
NLI_CACHE_ENABLED = os.getenv("NLI_CACHE_ENABLED", "1") not in {"0", "false", "False"}
NLI_CACHE_TTL_S = int(os.getenv("NLI_CACHE_TTL_S", "604800"))  # 7 gün


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

def is_clatter_gate_enabled() -> bool:
    """CLATTER entailment kapısı (opt-in, default 0).

    `CLATTER_GATE_ENABLED=1`: süre/eşik gerekçeli uygunluk-sonucu iddiaları
    (örn. "2 yıl → kıdem alabilirsiniz" / "2 yıl → yetersiz") için POZİTİF NLI
    entailment ŞART; neutral veya yalnız-fuzzy destek YETERSİZ sayılır → pass
    ENGELLENİR (retry varsa retry, yoksa reject). Çıkarım-halüsinasyonunun
    (CLAUDE.md §1) fuzzy'den kaçan en tehlikeli sınıfını kapatır.

    Default `0`: baseline davranış (1189-test) birebir korunur; mock/dev'de NLI
    yok → açılırsa yüksek-riskli iddialar entailment alamayıp over-reject olur,
    bu yüzden yalnız NLI yüklü production'da (VERIFY_STRICT ile birlikte) açılır.
    Yalnız pass→retry/reject yönünde SIKILAŞTIRIR (reject'i asla pass yapmaz).

    Dinamik okunur (is_verify_strict deseni) → testler monkeypatch.setenv ile toggle eder.
    SOTA: CLATTER (arXiv 2506.05243) neutral=not-supported → attribution 0.72→0.97.
    """
    return os.getenv("CLATTER_GATE_ENABLED", "0").lower() in {"1", "true", "yes"}


def get_ask_graph_timeout_s() -> float:
    """/ask + /ask/stream uçtan uca graph timeout (saniye). 0 = devre dışı.

    Hung bir graph (LLM server yanıtsız, MCP retrieval takılı, sonsuz retry)
    isteği süresiz açık tutup worker/connection tüketmesin diye üst sınır.
    İç node timeout'larından (HyDE 15s, OCR, mevzuat_node total ~40s) bağımsız
    son savunma hattı; aşılırsa /ask 504, /ask/stream timeout event döner.

    Default 180s: production p99 üstünde geniş bir tavan; mock graph testlerde
    ms'de biter, asla tetiklenmez (baseline korunur). Dinamik okunur ki testler
    `monkeypatch.setenv` ile küçük değere çekip timeout yolunu sınayabilsin.
    `ASK_GRAPH_TIMEOUT_S=0` ile tamamen kapatılabilir.
    """
    return float(os.getenv("ASK_GRAPH_TIMEOUT_S", "180"))


# --- Debate ---
DEBATE_REJECT_THRESHOLD = 0.30   # critique score < bu = hard reject
MAX_DEBATE_LOOPS = 2             # constitutional self-critique iter max

# --- Dilekçe Ajanı (6. ajan, want_dilekce=True + verdict=pass yolu) ---
# Default ON (kontrat: state.want_dilekce zaten False default; kapı runtime'da
# kontrol edilir). DILEKCE_ENABLED=0 ile node tamamen graph'tan dışlanır.
DILEKCE_ENABLED = os.getenv("DILEKCE_ENABLED", "1") not in {"0", "false", "False"}
# PDF byte tavanı (5MB) — reportlab patlamış template'te DoS riski.
DILEKCE_MAX_PDF_BYTES = int(os.getenv("DILEKCE_MAX_PDF_BYTES", "5242880"))
# DOCX byte tavanı (5MB) — python-docx editlenebilir Word çıktısı (vatandaş/avukat).
DILEKCE_MAX_DOCX_BYTES = int(os.getenv("DILEKCE_MAX_DOCX_BYTES", "5242880"))
# In-memory cache TTL (saniye) — kullanıcı PDF'i istediğinden uzun süre sonra
# açmasın diye 15 dk. Production'da Redis presigned URL ile değişebilir.
DILEKCE_CACHE_TTL_S = int(os.getenv("DILEKCE_CACHE_TTL_S", "900"))

# --- LLM ---
# Draft cevabı için üretim tavanı. Lokal 14B modelde asıl gecikme draft
# üretiminde olduğu için default "lean answer" profili kısa ama tam cevap verir.
# Derin/uzun yanıt gereken ortamda LLM_MAX_TOKENS=1000+ yapılabilir.
#
# 320 BİLİNÇLİ KORUNDU (A/B 2026-05-30, scripts/ab_llm_tokens.py):
#   240 token: P95 14.6s (320'ye göre -%23), cevap kesilme %0, kalite eşit.
#   320 token: P95 19.0s, cevap kesilme %0.
# Latans açısından 240 cazip GÖRÜNÜYOR ama YANLIŞ yön:
#   - Mevcut cevaplar zaten hedefin (160-220 kelime, draft.tr.txt) altında
#     (%100'ü < hedef, ort 45-117 kelime) → asıl kalite açığı "fazla kısa".
#   - Hedef-uzunluk cevap (~200 kelime) + [src:] etiketleri + başlık yapısı
#     Türkçe'de ~350-450 token tutar. 320 zaten hedef üst-sınırı için SIKI;
#     240 hedefin ALTINDA kapatır → kısalık sorununu kalıcılaştırır + ileride
#     prompt uzatılınca truncation yaratır.
#   - Doğru yön: prompt'u hedef-uzunluğa çekerken cap'i ~400'e ÇIKARMAK,
#     düşürmek değil. Latans 240 ile değil, model hızıyla (Qwen 7B / daha hızlı
#     GPU / quantization) çözülmeli.
# Latans-öncelikli dağıtımda LLM_MAX_TOKENS=240 env ile override edilebilir.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "320"))
# DRAFT cevabı zengin/yapısal format (Kısa cevap→Durumuna uygulama→Dayanak→Ne yapmalı→
# Dikkat→Güven, 240-360 kelime ≈ avukat ön-görüşmesi). 320 token bunu kesiyordu → 768.
# Yalnız draft_node kullanır; diğer LLM çağrıları (HyDE/MQ/clarifier) LLM_MAX_TOKENS'ta kalır.
# Latans ↑ (daha uzun üretim) ama kullanıcıya tam, uygulanabilir cevap. LATANS-öncelikli
# dağıtımda DRAFT_MAX_TOKENS=420 ile kısalt.
DRAFT_MAX_TOKENS = int(os.getenv("DRAFT_MAX_TOKENS", "768"))
# Debate JSON çıkışı gerçekte ~150 token (verdict+score+issues+rationale).
# 1536 yerine 350 → edge-case'lerde Qwen Çince sızıntısı veya verbose rationale
# önlenir; EOS erken ateşlerse sıfır etki. LLM_MAX_TOKENS'tan bağımsız ayarlanabilir.
DEBATE_MAX_TOKENS = int(os.getenv("DEBATE_MAX_TOKENS", "350"))
LLM_TEMPERATURE = 0.0            # hukuki üretim — deterministik ve düşük halüsinasyon
LLM_CONTEXT_BUDGET = 1400        # draft prompt'una ayrılan retrieval token bütçesi

# --- Uygunluk geçişi (yapılandırılmış akıl yürütme) ---
# Eşik-uygulama (kıdem 1 yıl, işe iade 6 ay+30 işçi) tek draft prompt'unda
# küçük modelde güvenilir olmuyor; ayrı, odaklı bir JSON-mode LLM çağrısı her
# madde için "eşik çıkar → olguyla karşılaştır → VAR/YOK" kararı üretir. Draft
# bu kararları prose'a çevirir. Lokal latency hedefi için default OFF; derin
# muhakeme istenen deployment'ta ELIGIBILITY_ENABLED=1 ile açılır.
ELIGIBILITY_ENABLED = os.getenv("ELIGIBILITY_ENABLED", "0") not in {"0", "false", "False"}
ELIGIBILITY_MAX_TOKENS = int(os.getenv("ELIGIBILITY_MAX_TOKENS", "700"))
# Not: 12-kanun seed sonrası retrieval blok büyüdü (8 law + 8 case × 600 char
# = ~10KB ≈ 2500 token). System+soru+template ile 4096 token llama-server -c
# default'unu aşıyordu (400 Bad Request). 3000'e düşürdük; 8 ref × ~1500 char
# ≈ 3000 token + 1000 sistem/template = 4000 → güvenli sınır içinde.

# --- HyDE & Multi-Query ---
HYDE_ENABLED = os.getenv("HYDE_ENABLED", "0") not in {"0", "false", "False"}
# Sprint-4 W1: 2.0s → 15.0s. Qwen 14B Q5_K_M ölçümü (v1 50 vaka, 2026-05-30):
# ortalama latans 4825ms (+4503ms vs baseline 322ms). A/B sonucu: domain@1 +2pp
# global; tüketici +12.5pp, kira +14.3pp, vergi +20pp — ama trafik -20pp, idari -17pp.
# Öneri: HYDE_ENABLED_DOMAINS ile alana özgü etkinleştir.
HYDE_TIMEOUT_S = float(os.getenv("HYDE_TIMEOUT_S", "15.0"))
HYDE_MAX_TOKENS = 200
# A/B bulgusu (2026-05-30): HyDE bu domainlerde pozitif, diğerlerinde negatif etki.
HYDE_ENABLED_DOMAINS: frozenset[str] = frozenset(
    os.getenv("HYDE_ENABLED_DOMAINS", "tuketici,kira,isHukuku,vergi,tapu").split(",")
)
MULTI_QUERY_ENABLED = os.getenv("MULTI_QUERY_ENABLED", "0") not in {"0", "false", "False"}
# Sprint-4 W1: 4 → 5. Literatürde N=5-8 standard, paraphrase çeşitliliği +Recall@20.
# Cache hit'lerde maliyetsiz. Per-paraphrase 1.5s + RRF merge yeterli.
MULTI_QUERY_N = int(os.getenv("MULTI_QUERY_N", "5"))
# A/B bulgusu (2026-05-30): MQ bu domainlerde pozitif, diğerlerinde negatif etki.
# trafik +20pp, kira +14.3pp, idari +0pp — tuketici -18pp, vergi -40pp.
MULTI_QUERY_ENABLED_DOMAINS: frozenset[str] = frozenset(
    os.getenv("MULTI_QUERY_ENABLED_DOMAINS", "trafik,kira,idari").split(",")
)

# --- Adaptive Routing ---
# Sorgu karmaşıklığı eşiği: bu değerin altındaki sorgular (kısa/spesifik/kanun referanslı)
# HyDE ve MQ'dan yararlanamaz. 0.4 = 5+ kelime, kanun kodu yok.
QUERY_COMPLEXITY_THRESHOLD = float(os.getenv("QUERY_COMPLEXITY_THRESHOLD", "0.4"))
# ADAPTIVE_ROUTING_ENABLED=1 → domain+complexity routing aktif (önerilen).
# =0 → eski davranış: HYDE_ENABLED/MULTI_QUERY_ENABLED global flag'leri direkt kullan.
ADAPTIVE_ROUTING_ENABLED = os.getenv("ADAPTIVE_ROUTING_ENABLED", "1") not in {"0", "false", "False"}
# Spekülatif arama: hybrid hemen başlar, HyDE/MQ bu süre içinde biterse kullanılır.
# Bitmezse hybrid sonucu döner. Kullanıcı max baseline + DEADLINE = ~2.3s bekler.
# A/B: HyDE ort. 4825ms → spekülatif mod ile ~322ms-2322ms aralığına çekilir.
SPECULATIVE_DEADLINE_S = float(os.getenv("SPECULATIVE_DEADLINE_S", "2.0"))
SPECULATIVE_ENABLED = os.getenv("SPECULATIVE_ENABLED", "1") not in {"0", "false", "False"}

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
        # Tüketici yönetmelikleri (seed_yonetmelik_direct ile eklendi)
        "YON_MESAFELI",     # Mesafeli Sözleşmeler Yönetmeliği
        "YON_GARANTI",      # Garanti Belgesi Yönetmeliği
        "YON_SSH",          # Satış Sonrası Hizmetler Yönetmeliği
        "YON_HAKEM",        # Tüketici Hakem Heyetleri Yönetmeliği (2022)
        "YON_HAKEM_ESKI",   # Tüketici Hakem Heyetleri Yönetmeliği (2014)
    ),
    "isHukuku":  (
        "IK",       # 4857 — İş
        "EIK",      # 1475 — Eski İş K. (m.14 kıdem tazminatı, hâlâ yürürlükte)
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
        "TMK",      # 4721 — Medeni (eşya hukuku, tescil m.705-706)
        "TBK",      # 6098 — Borçlar (satım sözleşmesi m.207+ — tapu devir ana akım)
        "TPK",      # 2644 — Tapu
        "KMK",      # 634 — Kat Mülkiyeti
        "IMARK",    # 3194 — İmar
        "KDK",      # 6306 — Kentsel Dönüşüm
        # KAMK (kamulaştırma) çıkarıldı — nadir, idari'ye ait; satış/tescil sorgusunda
        # _boost_by_domain ile öne çıkıp TMK/TBK satım maddelerini eziyordu (2026-06-04 ölçüm).
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

# Mevzuat law adaylarını cross-encoder ile yeniden sırala (RRF+boost heuristic'i
# yerine GERÇEK soru-belge alakası). "buzdolabı/ayıplı mal" sorusunda alakasız
# TTK (deniz ticareti) chunk'larını düşürüp TKHK m.11'i öne çıkarır. Default ON;
# test ortamı conftest ile "0" (BGE-reranker yüklenmesin).
MEVZUAT_RERANK_ENABLED = os.getenv("MEVZUAT_RERANK", "1").lower() in {"1", "true", "yes"}

# Domain çekirdek maddeleri — her domain'in EN kilit maddeleri (kanun_kodu, madde_no).
# Konuşma-dili sorguda cross-encoder noise-floor skor verince bu maddeler (örn. İş
# Hukuku ihbar tazminatı İK m.17) top-K'ya giremiyordu. Bu maddeler filtreyle çekilip
# aday havuzuna eklenir VE final çıktıda GARANTİ edilir — vatandaşın tipik sorularının
# yasal çekirdeği her zaman elde olsun. Yalnız MEVZUAT_DOMAIN_FILTER açıkken etkin.
DOMAIN_CORE_MADDELER: dict[str, tuple[tuple[str, int], ...]] = {
    "tuketici": (("TKHK", 8), ("TKHK", 11), ("TKHK", 13), ("TKHK", 15)),
    "isHukuku": (("IK", 17), ("IK", 18), ("IK", 25), ("EIK", 14)),
    "kira": (("TBK", 299), ("TBK", 315), ("TBK", 342), ("TBK", 344), ("TBK", 347), ("TBK", 350), ("TBK", 372)),
    # icra: m.62 = ödeme emrine 7 GÜNlük itiraz (vatandaş "borcum yok itiraz"ının doğru maddesi);
    # bu çapa eklenmeden m.62 aday havuzuna girmiyordu → yanlış süre/madde (2026-06-04 ölçüm).
    "icra": (("IIK", 62), ("IIK", 67), ("IIK", 89), ("IIK", 264)),
    # tapu: tescil talebi (TMK 705/706) + taşınmaz satış şekli (TBK 207/237) — satış/devir ana akım.
    "tapu": (("TMK", 705), ("TMK", 706), ("TBK", 207), ("TBK", 237)),
}

# Domain → ÖNCELİKLİ emsal mahkemesi (court-priority tier-sort).
# Corpus'ta Anayasa Mahkemesi bireysel-başvuru kararları hacimce baskın
# (~9:1 vs Yargıtay) → hybrid+cross-encoder emsalde anayasayı öne koyuyor.
# Vatandaş-yardım domain'lerinde esaslı emsal Yargıtay/Danıştay içtihadıdır;
# anayasa bireysel başvuru nadiren doğru emsal. Bu yüzden tier-0 = tercih edilen
# mahkeme(ler), tier-1 = diğer mahkemeler, tier-2 = anayasa (stable sort →
# cross-encoder sırası tier içinde korunur). DOMAIN_TO_KANUN_KODU/CORE ile
# aynı tier-sort felsefesi (mevzuat tarafındaki düzeltmenin emsal karşılığı).
DOMAIN_PREFERRED_COURTS: dict[str, tuple[str, ...]] = {
    # UYAP (Bölge Adliye + Asliye Mahkemesi, keyword-relevance araması) eklendi —
    # özel hukuk domain'lerinde Yargıtay ile birlikte tier-0; cross-encoder
    # tier içinde sıralar.
    "tuketici": ("yargitay", "uyap"),
    "isHukuku": ("yargitay", "uyap"),
    "kira": ("yargitay", "uyap"),
    "icra": ("yargitay", "uyap"),
    "trafik": ("yargitay", "uyap"),
    "tapu": ("yargitay", "danistay", "uyap"),
    "vergi": ("danistay", "gib_ozelge"),
    "idari": ("danistay",),
}

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
    "hapis cezası", "kasten yaralama", "taksirle yaralama",  # doğrudan ceza soruları
    "tutuklama", "tutuklu", "gözaltı",
    # Aile hukuku — çok-token form'lar
    "boşanma davası", "nafaka", "velayet", "evlat edinme",
    "aile hukuku", "aile mahkemesi",
)
