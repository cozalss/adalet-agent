"""Ajan zinciri sabitleri — tek yerden değişsin."""

from __future__ import annotations

import os

# --- Döngü kontrolü ---
MAX_RETRY = 3                    # debate → draft re-loop max
MIN_DOMAIN_CONFIDENCE = 0.35     # bu altına düşerse "netleştirin" reddi

# --- Selective prediction / abstention (FAZ 1.5, 2026-06-12) ---
# Verdict=pass olsa BİLE final güven skoru bu tabanın altındaysa cevabı reddet
# (abstain → "avukata danışın"). Hukuki güvenlikte recall>precision: belirsiz cevap
# vermektense çekilmek yeğdir. Default 0.0 = kapalı (mevcut davranış); production
# muhafazakâr ~0.40 (_compute_confidence tabanı). Env ile A/B (abstention curve).
ABSTAIN_CONFIDENCE_FLOOR = float(os.getenv("ABSTAIN_CONFIDENCE_FLOOR", "0.0"))

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
# Cited iddialarda (CITE_GROUNDING_CHECK) fuzzy TEK BAŞINA yetmez (misgrounding'i kapatmak için
# lettuce/NLI şart). AMA cite hedefine NEAR-VERBATIM (≥ bu yüksek bar) fuzzy = claim metni
# cited-source'ta birebir geçiyor demektir → grounded (yanlış-cite bu kadar yüksek fuzzy VEREMEZ).
# TR-NLI/lettuce zayıflığının false-drop'unu kurtarır. 0.92 = çok-yüksek bar (genel 0.45'in
# çok üstünde) → yalnız near-verbatim kabul; calibration-harness ile doğrulandı (FP artmaz).
CITE_FUZZY_HIGH_BAR = float(os.getenv("CITE_FUZZY_HIGH_BAR", "0.92"))
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


def _strict_default_flag(env_name: str) -> bool:
    """Production-aware savunma-bayrağı: VERIFY_STRICT=1 (NLI/Lettuce yüklü production)
    iken DEFAULT AÇIK, aksi halde (mock/dev/CI) kapalı → test baseline birebir korunur.

    Gerekçe (2026-06-12): CLATTER/CITE/partial-note kod-default 0 idi; production'da
    yalnız .env export'uyla açıktı → biri VERIFY_STRICT=1 koşup bu export'ları unutursa
    savunma SESSİZCE kapalı kalıyordu. Tek production sinyaline (VERIFY_STRICT) bağlanır.
    Explicit env override her zaman okunur (ablation/A-B korunur)."""
    default = "1" if is_verify_strict() else "0"
    return os.getenv(env_name, default).lower() in {"1", "true", "yes"}


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

    Default: VERIFY_STRICT-aware (production'da otomatik açık; mock/dev kapalı) — 2026-06-12.
    """
    return _strict_default_flag("CLATTER_GATE_ENABLED")


def is_llm_judge_enabled() -> bool:
    """OpenAI LLM-judge grounding kapısı (opt-in, default KAPALI).

    `VERIFY_LLM_JUDGE=1`: pass verdict'inde ek olarak OpenAI'ye "cevap kaynaklarla
    temellendirilmiş mi?" sorulur; DEĞİLSE pass ENGELLENİR (retry/reject). Yalnız
    SIKILAŞTIRIR (CLATTER gibi — reject'i ASLA pass yapmaz) → halüsinasyon kaçağı EKLEYEMEZ.
    Judge çökerse fail-OPEN (sıkılaştırmaz) → baseline NLI/lettuce verdict'i korunur.

    CLATTER'dan FARKLI: _strict_default_flag DEĞİL → production'da otomatik AÇILMAZ. Her
    istekte ekstra OpenAI çağrısı (gecikme+maliyet) + kalibrasyon A/B'si gerektirir
    (verify_calibration.py; quote-grounding A/B disiplini). Ölçmeden production'da açma.
    """
    return os.getenv("VERIFY_LLM_JUDGE", "0").lower() in {"1", "true", "yes"}


def is_llm_judge_high_risk_enabled() -> bool:
    """Yüksek-riskli sorularda (süre/zamanaşımı/hak-kaybı/icra) LLM-judge'u OTOMATİK aç —
    global VERIFY_LLM_JUDGE kapalı olsa bile. is_llm_judge_enabled gibi yalnız SIKILAŞTIRIR
    (reject'i pass yapmaz; fail-OPEN). Yanlış cevabın en zararlı olduğu konularda ekstra denetim.

    VERIFY_LLM_JUDGE_HIGH_RISK=1 ile etkin; default KAPALI. Global judge zaten açıksa (=1) bu
    no-op (her soru zaten denetleniyor). Yüksek-risk tespiti: is_high_risk_question().
    """
    return os.getenv("VERIFY_LLM_JUDGE_HIGH_RISK", "0").lower() in {"1", "true", "yes"}


# Yüksek-risk işaretleri — yanlış cevabın en zararlı olduğu konular (süre/hak-kaybı/icra).
# Tier routing (güçlü model) + judge-high-risk (ekstra denetim) AYNI sinyali paylaşır → tek kaynak.
# "süre" gibi çok-genel kelime BİLEREK dışarıda (her soruyu tetiklemesin); net yüksek-stake kalıplar.
_HIGH_RISK_KEYWORDS: tuple[str, ...] = (
    "zamanaşımı", "zaman aşımı", "tebligat", "tebliğ", "hak düşürücü", "itiraz süresi",
    "icra", "haciz", "ihtar", "temyiz", "istinaf", "hak kaybı", "hak kaybetme",
)
_HIGH_RISK_DOMAINS: frozenset[str] = frozenset({"icra"})


def is_high_risk_question(question: str | None, domain: str | None = None) -> bool:
    """Süre/hak-kaybı/icra gibi yüksek-riskli soru mu? Tier routing + judge-high-risk paylaşır.

    Saf + deterministik (LLM yok): yüksek-risk domain VEYA net hak-kaybı kelimesi. Türkçe
    küçük-harf normalizasyonu (I→ı, İ→i) ile diakritik-duyarsız eşleşme.
    """
    if domain and domain.lower() in _HIGH_RISK_DOMAINS:
        return True
    low = (question or "").replace("I", "ı").replace("İ", "i").lower()
    return any(kw in low for kw in _HIGH_RISK_KEYWORDS)


def is_partial_answer_note_enabled() -> bool:
    """Partial-answer dürüst notu (opt-in) — çok-konulu/çok-iddialı cevapta verify bazı
    iddiaları kaynaklayamayıp DÜŞÜRDÜYSE (finalize._filter_to_verified n_dropped>0), kullanıcıya
    'bazı noktaları doğrulayamadım, ayrıca sorun' notu eklenir → sessiz-eksiltme yerine ŞEFFAF.
    Grounding/sıfır-halüsinasyon DEĞİŞMEZ (ungrounded zaten gösterilmez); yalnız dürüst çerçeve.
    Call-time okunur (test toggle).

    2026-06-20 — DEFAULT KAPALI: kullanıcı "ne yazıyorsa o kalsın, 'Not:...' eklenmesin" dedi.
    Ayrıca finalize artık yalnız ÇELİŞEN cümleyi düşürür (orta yol) → n_dropped çoğunlukla 0.
    Açıkça PARTIAL_ANSWER_NOTE=1 yapılmadıkça gösterilmez."""
    return os.getenv("PARTIAL_ANSWER_NOTE", "0").lower() in {"1", "true", "yes"}


def is_emsal_live_fallback_enabled() -> bool:
    """Canlı emsal fallback (CRAG, opt-in, default 0) — corpus zayıfsa internetten dava çek.

    `EMSAL_LIVE_FALLBACK_ENABLED=1`: lokal emsal rerank skoru EMSAL_LIVE_TRIGGER_SCORE'un
    ALTINDAysa (corpus alakalı dava bulamadı), domain'e uygun CANLI yargı-mcp kaynağından
    aday çekilir + LOKAL reranker ile sıralanır (upstream relevance vermez, alakayı bizim
    cross-encoder verir). Eşik-üstü yoksa dürüst 'emsal yok' (SIFIR HALÜSİNASYON korunur;
    canlı snippet'ler verify'dan geçer). Network + latans → default kapalı; yalnız NLI/reranker
    yüklü production'da anlamlı. Dinamik okunur → testler monkeypatch.setenv ile toggle eder.

    DÜRÜST SINIR (ölçüldü): Tüketici Hakem Heyeti yargı-mcp'de YOK; en çok trafik
    (sigorta_tahkim) + vergi (gib_ozelge) gibi keyword-aranabilir kaynaklarda fayda sağlar.
    """
    return os.getenv("EMSAL_LIVE_FALLBACK_ENABLED", "0").lower() in {"1", "true", "yes"}


# Lokal emsal en-iyi rerank skoru bu değerin ALTINDAysa corpus 'zayıf' sayılır →
# canlı fallback tetiklenir. Cross-encoder sigmoid (0-1); 0.35 = zayıf-alaka eşiği.
# ÖLÇÜLDÜ BOZUK (2026-06-10 emsal-bench 64 vaka): 24 tetiklemenin 24'ü YANLIŞ ALARM
# (corpus alakalıydı — CE konuşma-dili TR'de noise-floor skor verir) ve tek gerçek
# topikal boşluk 0.802 skorla TETİKLENMEDİ → default mod 'coverage' (aşağıda); bu
# eşik yalnız EMSAL_LIVE_TRIGGER_MODE=score geri-uyumluluğunda kullanılır.
EMSAL_LIVE_TRIGGER_SCORE = float(os.getenv("EMSAL_LIVE_TRIGGER_SCORE", "0.35"))
# Canlı aday bir emsal olarak kabul edilmek için gereken min LOKAL-rerank skoru.
EMSAL_LIVE_MIN_SCORE = float(os.getenv("EMSAL_LIVE_MIN_SCORE", "0.30"))

# Canlı-fallback tetikleyici modu: 'coverage' (default, ölçülmüş) | 'score' (eski).
# coverage = sorgu içerik-kelimelerinin dönen kararlarca stem-aware kapsanması
# (retrieval.turkish_text.query_coverage) — skor kalibrasyonundan bağımsız sinyal.
EMSAL_LIVE_TRIGGER_MODE = os.getenv("EMSAL_LIVE_TRIGGER_MODE", "coverage").strip().lower()
# Kapsama bu değerin ALTINDAysa 'dönen kararlar sorguyla alakasız' sayılır → canlı
# fallback. KALİBRE EDİLDİ (2026-06-10, eval/runs/emsal_trigger_calib.json +
# off-corpus probe): 0.30 → kapsanan 64 vakada tetikleme 4/64 (%6.2; eski skor-eşiği
# 24/64=%37.5 idi) ve 6/6 off-corpus niş sorguda ateşlenir. Sınır-vakalar
# (abonelik/kargo/spor-salonu) önceki alaka-yargısında zaten zayıf ölçülen konular —
# orada tetiklenmek istenen davranış. Bilinen kör nokta: yanlış ALT-KONU (kapsama
# yüksek, konu yanlış) bu sinyalle görünmez — çözümü corpus kürasyonu.
EMSAL_LIVE_COVERAGE_MIN = float(os.getenv("EMSAL_LIVE_COVERAGE_MIN", "0.30"))


def is_guided_cite_enabled() -> bool:
    """Guided-decoding citation-whitelist (opt-in, default 0) — 2.2.

    `GUIDED_CITE_ENABLED=1`: claim-extraction LLM çağrısında JSON-schema → GBNF grammar
    ile `cite_id` alanı O turdaki retrieved `source_id` ENUM'una DECODE-seviyesinde
    kısıtlanır → uydurma cite ÜRETİLEMEZ (post-hoc filtreden önce; claim-cite kopukluğu
    olmadan iddia geçerli cite ile kalır → CITE_GROUNDING_CHECK ile sinerjik).

    Yalnız grammar destekleyen LLM'de (llamacpp / llamacpp_server) etkin; MockLLM yok sayar
    (json_mode davranışı korunur) → testler etkilenmez. known_ids boşsa schema kurulmaz
    (baseline). Dinamik okunur → testler monkeypatch.setenv ile toggle eder.

    SOTA: guided-decoding (arXiv 2404.08189) 0-shot %100 halüsinasyon → 1-shot %1.8.

    Default: VERIFY_STRICT-aware (production açık; MockLLM zaten yok sayar → test güvenli).
    """
    return _strict_default_flag("GUIDED_CITE_ENABLED")


def is_cite_grounding_check_enabled() -> bool:
    """Citation-grounding kontrolü (opt-in, default 0) — 'correct ≠ faithful'.

    `CITE_GROUNDING_CHECK=1`: cite_ids TAŞIYAN bir iddia için FUZZY eşleşme TEK BAŞINA
    "supported" sayılmaz; cite'ın işaret ettiği kaynak iddiayı GERÇEKTEN temellendirmeli
    (LettuceDetect grounding VEYA NLI entailment). 'Doğru madde-no + yanlış içerik atfı'
    (misgrounded citation — fuzzy yüzeysel kelime örtüşmesiyle geçen) yakalanır.

    pick_evidence zaten kanıtı cite hedefine daraltıyor; bu kapı yalnız "fuzzy yeter"
    yolunu cited iddialar için kapatır (lettuce/NLI grounding'i korur). Default `0`:
    baseline korunur; mock/dev'de NLI+lettuce yok → açılırsa over-reject → yalnız
    production'da (NLI yüklü, VERIFY_STRICT) açılır. CLATTER kapısıyla (is_clatter_gate_enabled)
    zincirlenir. Dinamik okunur → testler monkeypatch.setenv ile toggle eder.

    SOTA: Stanford-2024 / RAGAS faithfulness (arXiv 2412.18004) — misgrounded citation
    (gerçek kaynak ama desteklemiyor) daha tehlikeli/fark edilmesi zor.

    Default: VERIFY_STRICT-aware (production açık; mock/dev kapalı → baseline korunur).
    """
    return _strict_default_flag("CITE_GROUNDING_CHECK")


def is_quote_grounding_enabled() -> bool:
    """Kanıt-önce / quote-grounding draft talimatı (opt-in, default 0) — Anthropic finding-3.

    `DRAFT_QUOTE_GROUNDING=1`: draft system prompt'una ek bir kural eklenir — model her hukuki
    iddiayı yazmadan ÖNCE o iddiayı DOĞRUDAN destekleyen ifadenin verilen kaynak metninde
    gerçekten bulunduğunu içsel olarak doğrular; bulamazsa iddiayı yazmaz. Çıktı FORMATI değişmez
    (ayrı 'alıntı bloğu' üretilmez → BLUF-promote/bölüm-parse/citation pipeline aynen korunur);
    yalnız mevcut kural 1-2'nin (kaynak-dışı üretme) kanıt-önce pekiştirmesidir.

    Kaynak: Anthropic resmi 'reduce hallucinations' dokümanı + prompt-engineering kursu
    ('extract word-for-word quotes first... if you can't find relevant quotes, say so';
    deep-research 3-0 yüksek-güven, RAG için en kritik teknik). MockLLM system prompt'u yok
    sayar → testler etkilenmez. Dinamik okunur → testler monkeypatch.setenv ile toggle eder.

    Default 0 (DENEYSEL, ÖLÇÜLMEDİ): davranışsal etki GPU harness (test_answers.py) ile
    ölçülmeli; latency/uzunluk etkisi olabilir. Açılmadan SIFIR davranış değişikliği (baseline).
    """
    return os.getenv("DRAFT_QUOTE_GROUNDING", "0").lower() in {"1", "true", "yes"}


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
# ADAPTİF UZUNLUK (2026-06-05): sabit cap yerine soru-karmaşıklığına göre token bütçesi
# (draft._adaptive_max_tokens). DRAFT_MAX_TOKENS = karmaşık/olgu-zengin TAVAN (kesilmesin →
# 768→960); DRAFT_MIN_TOKENS = basit/tanımsal soru tavanı (gereksiz uzunluğu/RLHF-verbosity'i kıs).
# Gerçek uzunluğu prompt sürer (model basitte erken durur); bunlar yalnız tavan/taban.
# max(128, ...) alt sınır (ECC sweep): geçersiz/0/negatif env max_tokens=0 → llama.cpp hatası yapmasın.
# 2026-06-20: EĞİTİCİ/kapsamlı cevap için tavan yükseltildi (896→1500). Kullanıcı "çok az yazı,
# öğrenemiyorum" dedi; gpt-4o hızlı olduğundan uzun üretim latansı kabul edilebilir. Latans-öncelikli
# dağıtımda DRAFT_MAX_TOKENS env ile kısaltılabilir.
DRAFT_MAX_TOKENS = max(128, int(os.getenv("DRAFT_MAX_TOKENS", "1500")))
# Guard (ECC review MEDIUM-1): yanlış env (MIN>MAX) tavanı tersine çevirmesin → MAX'e clamp; alt 64.
# MIN de yükseltildi (384→640): basit soruda bile kuralı yeterince açıklasın (kullanıcı öğrensin).
DRAFT_MIN_TOKENS = max(64, min(int(os.getenv("DRAFT_MIN_TOKENS", "640")), DRAFT_MAX_TOKENS))
# Doğrulanacak iddia tavanı (NLI çift sayısını → verify latency'sini doğrudan etkiler).
# 15→12: tipik hukuk cevabı ~5-9 iddia; üst kuyruk nadiren bilgi taşır, NLI yükü lineer.
# MIN_VERIFIED_CLAIMS_RATIO koruması yerinde → kapsama düşmez. Env ile ayarlanabilir.
DRAFT_MAX_CLAIMS = max(4, int(os.getenv("DRAFT_MAX_CLAIMS", "12")))
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

# --- Tiered LLM routing (model kademesi) ---
# LLM_TIER_ROUTING=1 → karmaşık (olgu-zengin/uzun) VEYA yüksek-riskli sorular GÜÇLÜ modele
# (OPENAI_LLM_MODEL_COMPLEX, default gpt-4o), basit sorular varsayılan modele (OPENAI_LLM_MODEL,
# gpt-4o-mini) gider. Yalnız LLM_MODE=openai'de etkili (lokal/mock tek model). Default KAPALI —
# gpt-4o ~16× gpt-4o-mini maliyetli; ölçerek aç (yalnız karmaşık/riskli soruda devreye girer).
OPENAI_LLM_MODEL_COMPLEX = os.getenv("OPENAI_LLM_MODEL_COMPLEX", "gpt-4o").strip() or "gpt-4o"


def is_tier_routing_enabled() -> bool:
    """Zorluğa/riske göre model kademesi (LLM_TIER_ROUTING=1; default KAPALI)."""
    return os.getenv("LLM_TIER_ROUTING", "0").lower() in {"1", "true", "yes"}

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
        "YON_ETIKET", "YON_ONODEME",  # Firecrawl ingestion
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
        # Yönetmelikler (Firecrawl ingestion — seed_firecrawl_yonetmelik)
        "YON_ISG_RISK", "YON_ISG_HIZMET", "YON_ISG_EGITIM", "YON_ISKUR",
    ),
    "kira":      (
        "TBK",      # 6098 — Borçlar (kira bölümü)
        "TMK",      # 4721 — Medeni (mülkiyet)
        "KMK",      # 634 — Kat Mülkiyeti
        "KDK",      # 6306 — Kentsel Dönüşüm
        "BLDK",     # 5393 — Belediye
        "YON_KMK",  # Kat Mülkiyeti Yönetmeliği (Firecrawl ingestion)
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
        "KABAHAT",  # 5326 — Kabahatler (trafik idari para cezasına itiraz usulü)
        "SIGORTA",  # 5684 — Sigortacılık (ZMSS)
        "TBK",      # 6098 — Borçlar (haksız fiil)
        "SGK",      # 5510 — Kaza tazminat
        "KGK",      # 4925 — Karayolu Taşıma
        # Yönetmelikler (Firecrawl ingestion)
        "YON_TRAFIK", "YON_ARAC_TESCIL",
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
        "YON_TAPU_SICIL",  # Tapu Sicili Tüzüğü (Firecrawl ingestion)
    ),
    "idari":     (
        "IYUK",     # 2577 — İdari Yargılama
        "KABAHAT",  # 5326 — Kabahatler (idari para cezası + sulh ceza hakimliğine itiraz)
        "DMK",      # 657 — Devlet Memurları
        "MYK",      # 5018 — Mali Yönetim
        "IHK",      # 4734 — Kamu İhale
        "IHSK",     # 4735 — İhale Sözleşmeleri
        "DIHK",     # 3071 — Dilekçe Hakkı
        "BLDK",     # 5393 — Belediye
        "IOIK",     # 5302 — İl Özel
        "CK",       # 2872 — Çevre
        # KAMK tapu'dan çıkarılmıştı ('idari'ye ait' notuyla) ama idari'ye hiç
        # eklenmemişti → kamulaştırma soruları boost'suz/tier-2 kalıp sistematik
        # miss veriyordu (2026-06-11 teşhis: V_idari_004 + V3_idari_023/024 hepsi KAMK).
        "KAMK",     # 2942 — Kamulaştırma (bedel tespiti m.10-11, acele m.27)
        # Yönetmelikler (Firecrawl ingestion)
        "YON_IMAR", "YON_CED",
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
    # TKHK 48 (taksitli/mesafeli satış — gold v2 freq 7, en-sık 2.) eklendi; 5 çapa/8 slot, yer var.
    # TKHK 68 (tüketici hakem heyeti parasal sınır/başvuru — yaygın, prod-recall miss) eklendi.
    # TKHK 31 (tüketici kredisi/cayma), 47 (devre tatil), 70 (paket tur) eklendi (2026-06-18
    # query-priority kürasyonu): retrieval'da kaçıyordu ama yaygın vatandaş konusu + spesifik keyword.
    "tuketici": (("TKHK", 8), ("TKHK", 11), ("TKHK", 13), ("TKHK", 15), ("TKHK", 31),
                 ("TKHK", 47), ("TKHK", 48), ("TKHK", 68), ("TKHK", 70)),
    # IK 41 (fazla çalışma) eklendi: ölçüldü (iter13) "fazla mesai ödemiyor" → m.25 (fesih)
    # cite ediliyordu (yanlış madde üste çıkıyor) → verify düşürüyordu. 32=ücret, 53=yıllık izin
    # de tipik isHukuku çekirdeği. Garanti-yüzeye-çıkar (icra m.62 ile aynı kanıtlı pattern).
    "isHukuku": (("IK", 17), ("IK", 18), ("IK", 25), ("IK", 32), ("IK", 41), ("IK", 53), ("EIK", 14)),
    # TBK 325 (erken tahliye+kira borcu), 352 (iki haklı ihtar/temerrüt tahliyesi),
    # 584 (eş rızası-kefalet) eklendi (2026-06-18 query-priority kürasyonu): yaygın + spesifik keyword.
    "kira": (("TBK", 299), ("TBK", 315), ("TBK", 325), ("TBK", 342), ("TBK", 344),
             ("TBK", 347), ("TBK", 350), ("TBK", 352), ("TBK", 372), ("TBK", 584)),
    # icra: m.62 = ödeme emrine 7 GÜNlük itiraz (vatandaş "borcum yok itiraz"ının doğru maddesi);
    # bu çapa eklenmeden m.62 aday havuzuna girmiyordu → yanlış süre/madde (2026-06-04 ölçüm).
    # IIK 82 (haczedilemezlik — "maaşıma/evime haciz" vatandaş sorusu, gold v2 freq 3) eklendi.
    # IIK 72 (menfi tespit / istirdat davası — yaygın vatandaş konusu, prod-recall miss) eklendi.
    # IIK 285 (ihtiyati haciz) eklendi (2026-06-18 query-priority kürasyonu): "ihtiyati haciz"
    # vatandaşın aynen kullandığı spesifik terim; retrieval kaçırıyordu.
    "icra": (("IIK", 62), ("IIK", 67), ("IIK", 72), ("IIK", 82), ("IIK", 89), ("IIK", 264), ("IIK", 285)),
    # tapu: tescil talebi (TMK 705/706) + taşınmaz satış şekli (TBK 207/237) — satış/devir ana akım.
    # TMK 1023 (tapu siciline güven — iyiniyetli iktisap, tapu davalarının çekirdeği) eklendi.
    # TMK 575 (muris muvazaası/tenkis) + 698 (izale-i şuyu/ortaklığın giderilmesi) — çok yaygın
    # tapu-miras davaları, prod-recall miss → eklendi (7 çapa/8, miras+satış+sicil+izale kapsar).
    "tapu": (("TMK", 575), ("TMK", 698), ("TMK", 705), ("TMK", 706), ("TMK", 1023), ("TBK", 207), ("TBK", 237)),
    # idari/trafik/vergi: ÇAPASIZdı (0 anchor) → en-sık beklenen maddeler (gold v2 frekansı)
    # eklendi; 2-3 çapa TOP_K_LAW=8'de crowding yapmaz, sorgu-özel maddeye yer kalır (over-anchor
    # riski yok — 0'dan başlıyor). idari: IYUK 7=dava süresi(60g), 11=üst makama başvuru.
    "idari": (("IYUK", 7), ("IYUK", 11)),
    # trafik: KTK 85=işletenin sorumluluğu, 91=zorunlu mali sorumluluk sigortası, 98=sağlık giderleri.
    # KTK 56 (manevi/maddi tazminat — trafik kazası tazminat çekirdeği, prod-recall miss) eklendi.
    # TBK 53 (ölümde destekten yoksun kalma tazminatı — ayrı kanun) eklendi (2026-06-18
    # query-priority): ölümlü trafik kazası tazminatının çekirdek maddesi, retrieval kaçırıyordu.
    "trafik": (("KTK", 56), ("KTK", 85), ("KTK", 91), ("KTK", 98), ("TBK", 53)),
    # vergi: VUK 29=tarh, 344=vergi ziyaı cezası (en-sık "ceza/tarhiyat" çekirdeği; diğer slotlar
    # KDV/emlak/MTV sorgu-özel maddelere kalır).
    # VUK 378 (ihtirazi kayıt / dava açma — yaygın vergi-itiraz konusu, prod-recall miss) eklendi.
    "vergi": (("VUK", 29), ("VUK", 344), ("VUK", 378)),
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
    "vergi": ("danistay", "gib_ozelge", "sayistay"),
    # Sayıştay (kamu mali denetimi) idari + vergi emsali; corpus'ta 231 chunk var ama
    # emsal kaynak setinde olmadığı için hiç yüzeye çıkmıyordu (2026-06-04 fix) → tier-0.
    "idari": ("danistay", "sayistay"),
}

# Domain → DOĞRU Yargıtay dairesi (chamber-priority alt-tier, P9 2026-06-11).
# ÖLÇÜLDÜ: tuketici emsal top-3'ün 20/24'ü 11. HD (ticaret/sigorta dairesi) —
# gerçek tüketici daireleri (3./13. HD, HGK) 1/24. Corpus'ta 888 adet 13. HD
# tuketici chunk'ı VAR ama hacim-baskın 11. HD'nin altında kalıyor. Court-tier
# İÇİNDE ikincil sıralama: tercih edilen daire öne (stable — CE sırası korunur).
# Yalnız ölçülmüş-problemli domain'ler; yenisini eklemeden ÖNCE eval_emsal ile ölç.
DOMAIN_PREFERRED_CHAMBERS: dict[str, tuple[str, ...]] = {
    "tuketici": ("3. Hukuk Dairesi", "13. Hukuk Dairesi", "Hukuk Genel Kurulu"),
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
    # Boşanma/eş bağlamı (çok-token, FP önle: "evlilik sözleşmesi" tüketici değil)
    "boşanmak isti", "boşanma sürec", "eşimden boşan", "eşinden boşan",
    # Fikri mülkiyet — çok-token form'lar (tek-token patent/telif triaj prefix-set'te).
    "fikri mülkiyet", "marka tescil", "marka hakk", "faydalı model", "tasarım tescil",
    # Dijital varlık — çok-token (tek-token kripto/bitcoin/metaverse prefix-set'te).
    "sanal arsa", "sanal para",
    # Göçmenlik — çok-token (tek-token vatandaşlık/sığınma/göçmen prefix-set'te).
    "oturma izni", "oturum izni", "pasaport başvuru",
)
