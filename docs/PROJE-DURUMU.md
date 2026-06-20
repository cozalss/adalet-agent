# ADALET-AGENT — Proje Durumu: Şu Ana Kadar Yapılan Her Şey

> **Bu belge** projenin baştan beri (tüm oturumlar) gerçekleştirilen işin sadık,
> birleşik kaydıdır. Kaynak: 220 commit'lik git geçmişi + oturumlar-arası geliştirme
> notları + as-built kod. Vizyon/kurallar için `../CLAUDE.md`; değişiklik dökümü için
> `DEGISIKLIK-GUNLUGU.md`; mimari detay için `architecture.md` ve `decisions/ADR-*`.
>
> Son güncelleme: 2026-06-03 · Durum: çekirdek pipeline + retrieval + tahmin + güvenlik
> + frontend/auth tamamlandı ve ölçümle doğrulandı.

## İçindekiler

1. [Genel Bakış ve Mimari](#1-genel-bakış-ve-mimari)
2. [Sıfır-Halüsinasyon ve Doğrulama (Verify)](#2-sıfır-halüsinasyon-ve-doğrulama-verify)
3. [Bilgi Erişimi (Retrieval / RAG)](#3-bilgi-erişimi-retrieval--rag)
4. [Dava-Sonucu Tahmini (Faz-5)](#4-dava-sonucu-tahmini-faz-5--silver-yanılsaması-destanı)
5. [Akıllandırma Fazları (Faz-1..5) ve Değerlendirme](#5-akıllandırma-fazları-faz-15-ve-değerlendirme)
6. [Frontend, Kimlik Doğrulama, Supabase ve Çok-Modluluk](#6-frontend-kimlik-doğrulama-supabase-ve-çok-modluluk)
7. [Güvenlik, Gözlemlenebilirlik, Deployment ve Bilinen Boşluklar](#7-güvenlik-gözlemlenebilirlik-deployment-ve-bilinen-boşluklar)

---
## 1. Genel Bakış ve Mimari

### 1.1 Vizyon

ADALET-AGENT, avukat tutamayan Türk vatandaşlarına (tüketici, işçi, kiracı; sivil hukukta toplam 8 alan) **doğrulanmış**, **uydurmayan** ve **çok-modlu** (yazılı + sesli + belge fotoğrafı) bir yapay zeka hukuk asistanı sunar. Mevcut genel amaçlı LLM çözümlerinin (ChatGPT, Gemini) hukukta tehlikeli olan **yasa/karar uydurma** sorununa, **iddia-doğrulamalı çoklu-ajan** mimarisiyle yanıt verir.

Sistemin kırmızı çizgisi **sıfır halüsinasyon**dur: hiçbir ajan, kaynağı doğrulanmamış bir hukuki iddia üretemez. Her yasal referans Qdrant korpusundan getirilen orijinal metinle eşleştirilir; doğrulanamayan iddia reddedilir. Sistem yalnızca **8 sivil hukuk alanında** çalışır (`tuketici · isHukuku · kira · icra · trafik · vergi · tapu · idari`); ceza ve aile hukuku bilinçli olarak kapsam dışıdır (triaj `unknown`/`out_of_scope_sensitive` döndürür).

### 1.2 Üç Katmanlı Mimari

Sistem klasik bir **Giriş → AI Beyin → Çıkış** akışı üzerine kuruludur:

| Katman | Bileşenler |
|--------|-----------|
| **Giriş** | Web (`frontend/` — Vite 6 + React 18, elle CSS), Mobil (Flutter — planlı), B2B HTTP. Ön-işleme: OCR (Tesseract → `ImageAttachment`), STT (Whisper → `audio_transcript`), metin normalize. |
| **AI Beyin** | FastAPI kenar katmanı (Auth/JWT · Sanitize · PII-mask · Rate-limiter · Audit) + **LangGraph** çoklu-ajan boru hattı + **V2 karar katmanı** (Policy Engine + Clarifier + Composer). |
| **Çıkış** | Yazılı cevab (Web + Mobil), sesli okuma (TTS), indirilebilir dilekçe (PDF + editlenebilir DOCX). Her yanıt: güven skoru + ajan-izi şeffaflık paneli + zorunlu hukuki sorumluluk reddi. |

> Not: Üst düzey vizyon dokümanı web istemcisini Next.js olarak tanımlasa da, gerçek implementasyon **Vite + React (JS/JSX)** ile yapıldı; prototip 1:1 korundu (kaynak: hafıza `sor-frontend-and-backlog`, `frontend/`).

### 1.3 LangGraph Çoklu-Ajan Boru Hattı

Orkestratör **LangGraph** `StateGraph`'tır; tüm ajanlar `AgentState` (TypedDict) paylaşır. Paralel ajanların (Mevzuat + Emsal) aynı state'e fan-in yapabilmesi için citation listeleri `merge_citations` reducer'ı (source_id union-dedup) ile birleştirilir. Çekirdek **7 ajan** + opsiyonel **8. ajan (Tahmin)**:

| # | Ajan (node) | Görev |
|---|-------------|-------|
| 1 | **Triaj** | Soruyu 8 domain + `unknown`'a sınıflandırır; ek olarak `response_intent` (legal_answer / smalltalk / out_of_scope_sensitive / redirect / needs_clarification) ve `case_facts` (süre, işçi sayısı, tutar, olay…) çıkarır. |
| 2 | **Mevzuat** | İlgili kanun maddelerini hybrid retrieval ile getirir (TOP_K_LAW=8); domain-aware boost + çekirdek-madde garantisi uygular. |
| 3 | **Emsal** | Benzer Yargıtay/Danıştay kararlarını getirir (TOP_K_CASE=8); court-priority tier-sort + opsiyonel GraphRAG k-hop komşu genişletme. |
| 4 | **Draft** | Lokal Qwen ile, getirilen kaynaklara dayalı yapısal Türkçe cevabı yazar (Kısa cevap → Durumuna uygulama → Dayanak → Ne yapmalı → Dikkat → Güven). |
| 5 | **Verify** | Her iddiayı 4 katmanda doğrular: L1 kurallar → L2 fuzzy (≥0.45) → L2.5 LettuceDetect → L3 NLI (entailment ≥0.55 / contradiction-veto ≥0.70). Doğrulanmayan iddia "unverified". |
| 6 | **Debate** | Constitutional self-critique ile diğer ajanların çıktısını hakemler; `pass / retry / reject` verdict üretir. |
| 7 | **Finalize** | Güven skorunu hesaplar, zorunlu disclaimer'ı ekler, nihai yanıtı oluşturur. |
| 8 | **Tahmin** (opt-in) | `PREDICTIVE_ENABLED=1` ile dava sonucu eğilimini tahmin eder (heuristic emsal-oylaması / BERT-TR). Yalnız **display-only**, güven ≤0.85, min-emsal guard (`_MIN_SIGNAL=2`); verify/debate hard-gate'i bundan etkilenmez. |

Ek opsiyonel SOTA node'ları (default OFF, ENV-gated): **CRAG** (`mevzuat+emsal` fan-in sonrası düşük-confidence düzeltme), **Self-RAG** (debate sonrası reflection-token override), **Eligibility** (`ELIGIBILITY_ENABLED=1` ile her madde için eşik-uygunluk JSON kararı), **Dilekçe** (`want_dilekce=True` + verdict=pass yolunda PDF/DOCX taslak). Tüm bayraklar kapalıyken graph topolojisi Sprint-3/4 baseline ile birebir aynıdır.

### 1.4 V2 Karar Katmanı — Policy Engine + Clarifier + Composer

Sprint-4 boru hattı her soruyu doğrudan retrieval→draft'a sokuyordu. V2 (2026-05), üretimden **önce** "ne yapmalı?" kararını tek bir deterministik, **LLM'siz** yere topladı:

- **Policy Engine** (`agents/policy.py`): `decide_path(state) → answer | clarify | redirect | reject_sensitive | smalltalk` saf fonksiyonu (aynı state → aynı karar). Karar artık triaj/verify/debate'e dağılmış değil. Deterministik merdiven: smalltalk → reject_sensitive → unknown-redirect → loop-guard → clarifier-cevabı algılama → kısa durumsal şikâyet → olgu-yeterliliği (`REQUIRED_FACTS` + `MIN_FACTS_FOR_ANSWER`) → genel/tanımsal soru → clarify.
- **Clarifier** (`agents/nodes/clarifier.py`): Policy "clarify" derse, retrieval/draft'a **hiç dokunmadan** finalize'a akar. Sorular domain başına SABİT bir bankadan (`QUESTION_BANK`) gelir → **sıfır halüsinasyon yüzeyi** (hiç madde/karar numarası yok). `CLARIFY_MARKER` ile loop-guard (`MAX_CLARIFICATION_ROUNDS=1`); turn-2 domain devralma ile multiturn doğruluğu %45→%100.
- **Composer** (`agents/nodes/compose.py`): Karar VERMEZ; yalnız belirli intent'lerde (`redirect_to_scope`) kullanıcıya görünen metni LLM ile daha doğal yazar, başarısız olursa deterministik fallback'e düşer. Hukuki cevap yolunda **no-op** (`return {}`) → baseline davranış korunur.

### 1.5 Uçtan Uca Veri Akışı

```
İstemci → Caddy (TLS) → Auth (JWT/API-Key) → Sanitize → PII-mask → Rate-limit → Audit
   │
   ▼
triaj (domain + response_intent + case_facts)
   │  decide_path(state)   ← deterministik, LLM yok
   ├─ smalltalk / reject_sensitive → finalize (hazır metin)
   ├─ redirect                      → compose → finalize
   ├─ clarify                       → clarifier → finalize (sorular, durur)
   └─ answer  → [mevzuat ‖ emsal] (paralel hybrid retrieval)
                  → [eligibility?] → draft (Qwen)
                  → verify (4 katman) → debate (constitutional)
                       │ retry → mevzuat+emsal RE-RETRIEVE (MAX_RETRY=3 guard)
                       └ pass/reject → [tahmin?] → [dilekçe?] → compose(no-op) → finalize
```

Retry, basitçe draft'a dönmek yerine **yeniden retrieve** eder (HyDE/multi-query stokastik olduğundan farklı/daha alakalı kaynak getirebilir); `merge_citations` dedup ref birikmesini önler. `MAX_RETRY` guard döngüyü kapatır.

**SSE akış sözleşmesi:** `POST /ask/stream` graph'ı tek kez `astream(stream_mode="values")` ile çalıştırır; event'ler `node · triage · clarify · sources · drafting · final · error` (ara payload'lar `v: 1` schema versiyonu taşır).

### 1.6 Teknoloji Yığını

Lokal + bulut **hibrit** model desteği (v2.3: lokal-only zorunluluğu kaldırıldı). Tam-lokal mod (yerel, hızlı, gizli) gizlilik/offline için mevcut; en yüksek kalite gereken yerde bulut API'ler kullanılabilir (anahtarlar `.env`'de):

| Katman | Teknoloji |
|--------|-----------|
| **Ana LLM** | **Qwen3.5-9B** UD-Q4_K_XL (GGUF) — `llama-cpp-python` (cu124), GPU offload ~23 tok/s (RTX 4070 12GB), Gated DeltaNet, 262k ctx, Apache-2.0. *Erken E2E/ablation ölçümleri (~50s, 2026-05) Qwen 2.5 14B Q5_K_M üzerindeydi; üretim 2026-06'da head-to-head (2-1) sonrası 9B'ye geçti — güncel kaynak `.env.example`/README.* |
| **Backend / Orkestrasyon** | FastAPI (Python 3.11) + LangGraph |
| **Vector DB** | Qdrant — production koleksiyonu `adalet_mursit_hybrid` (Mursit 768-dim dense + BGE-M3 sparse, 159.638 nokta) |
| **Embedding** | `newmindai/Mursit-Base-TR-Retrieval` (768-dim) + `BAAI/bge-m3` sparse (vergi/trafik/icra için) |
| **Retrieval** | Hybrid (dense + sparse + RRF k=60) + HyDE + Multi-Query (domain-aware, spekülatif 2s deadline) + `bge-reranker-v2-m3` (max_length=512) |
| **Verify** | mDeBERTa NLI + LettuceDetect + RARR-lite |
| **Multimodal** | Tesseract 5 (OCR) · Whisper (STT) · Piper/Coqui (TTS) |
| **İlişkisel DB** | PostgreSQL (feedback/api_key/audit/conversation/user_account, env-gated, Alembic) + Supabase (auth/geçmiş/tercih, v2.2) |
| **Frontend** | Vite 6 + React 18 (JS/JSX, elle CSS) — SSE ile backend'e bağlı |
| **Cache / DevOps** | Redis (session + rate-limiter) · Docker · GitHub Actions · Caddy 2 (auto-TLS) · Hetzner |
| **Gözlemleme** | Langfuse · Ragas (RAG eval) |

**Ölçülen retrieval performansı** (186 vaka, production konfig): domain@1 %79.6 · @5 %96.8 · kanun@5 %50.5 · P95 46ms (Mursit); BGE-M3 ile karşılaştırmada kanun@5 +7pp, latans −42%, vergi +36pp. Toplam **771+ backend testi**, mypy --strict 0 hata.

## 2. Sıfır-Halüsinasyon ve Doğrulama (Verify)

ADALET'in tek bozulmaz kırmızı çizgisi: **kaynağı doğrulanmamış hiçbir hukuki iddia kullanıcıya gitmez** (CLAUDE.md §1). Her yasal referans `mevzuat.gov.tr` veya `yargi-mcp`'den getirilen orijinal metinle eşleştirilir; doğrulanamayan iddia ya taslaktan çıkarılır ya da cevap tamamen reddedilir. Bu bölüm, bu çizgiyi hayata geçiren çok-katmanlı doğrulama hattını, fail-closed veto detektörlerini, NLI eşik kalibrasyonunu ve ölçülmüş başarıyı belgeler.

### 2.1 Çok-katmanlı Verify hattı

`verify_node` (`backend/agents/nodes/verify.py`), LLM'in ürettiği her iddiayı (claim) dört bağımsız katmandan geçirir. Katman mantığı okunabilirlik için `agents/verifier_layers.py` modülüne ayrıştırılmıştır (Sprint-4 W4.1 split).

| Katman | Yöntem | Görev |
|--------|--------|-------|
| **L1 — Rules** | Madde/karar regex sentaktik geçerlilik | "m. 11", "m-IK-21", esas/karar no formatı doğru mu; "madde" geçip numara yoksa şüpheli işaretle |
| **L2 — Fuzzy** | rapidfuzz (`partial_ratio` ∨ `token_set_ratio`) | İddia metni kaynak snippet'iyle pozitif örtüşüyor mu (≥ `FUZZY_SUPPORT_THRESHOLD` 0.45) |
| **L2.5 — LettuceDetect** | Token-düzey grounding | İddia kaynakta token bazında temellendiriliyor mu; `< 0.15` → soft veto, `≥ 0.45` → destek |
| **L3 — NLI** | mDeBERTa XNLI (entailment/contradiction) | İddia kaynakla **çelişiyor mu** (`con ≥ 0.70` → hard veto); `ent ≥ 0.55` → entailment desteği |
| **L4 — RARR** | Evidence augmentation | Opt-in (`RARR_ENABLED=1`), kanıt zenginleştirme |

Katman çağrıları yan-etkisiz ve paralel-güvenlidir: L1/L2 saf-Python (inline, hızlı); L2.5 ve L3 model-ağırlıklı olduğundan `asyncio.gather` + `to_thread` ile eşzamanlı koşturulur (yavaş NLI forward'ı arkada "bedava" çalışır). NLI sonuçları `verifier/cache.py` ile cache'lenir — deterministik (temp=0) olduğundan aynı `(claim, evidence)` çifti tekrar modele gönderilmez.

**Kanıt-daraltma (Step-4 sıkılaştırma):** Bir iddia belirli bir madde no söylüyorsa (`_scope_refs_to_claim_madde`), doğrulama kanıtı O maddenin kaynağına daraltır. İddia, retrieve edilmemiş bir maddeye atıf yapıyorsa (`stated_but_missing`) fuzzy skoru doğrudan `0.0` → uydurma atıf yakalanır. Böylece LLM bir maddenin içeriğini başka maddeye atfederse (garbled m.31), yanlış snippet'le gevşek token örtüşmesi üzerinden geçemez.

### 2.2 Fail-closed davranış (graceful degrade değil)

Production'da `VERIFY_STRICT=1` zorunludur. Strict modda zorunlu bir doğrulayıcı (NLI veya LettuceDetect) çökerse `VerifierUnavailableError` fırlatılır; `verify_node` bunu yakalar ve cevabı **fail-closed reddeder** — doğrulayıcı çalışmadıysa hiçbir iddia "doğrulanmış" sayılamaz. Aynı şekilde retrieval hiç kaynak getirmezse (`not refs`) tüm iddialar "Kaynak yok" ile işaretlenip verdict `reject` olur. Sessiz pas yoktur.

### 2.3 risk_guard — içerik-risk veto detektörleri

NLI yalnız **doğrudan çelişki** yakalar. Ama `[src:]` etiketli olduğu için NLI/fuzzy'den geçen, kaynak sessiz kaldığında flag almayan tehlikeli **yanlış çıkarımlar** vardır. `backend/agents/risk_guard.py` (`verify_risk_veto`, verify_node satır 204'te çağrılır) bu sınıfları yakalayıp **fail-closed REJECT** verir. Sıcaklık 0'da retry aynı çıktıyı üreteceği için retry değil, doğrudan reddedilir.

Üç yüksek-kesinlikli bloklayıcı detektör:

| Detektör | Yakaladığı | Örnek | Sınır |
|----------|-----------|-------|-------|
| `fabricated_law_names` | Uydurma/yanlış kanun adı | "İşçilik Kanunu" (gerçek: İş Kanunu), "Kiralama Kanunu", "Tüketicilik Kanunu" | Yalnız kesin-yanlış `-cilik/-lama` kökleri; geçerli halk-dili adlar ("Borçlar Kanunu") eklenmez (FP önle) |
| `negative_eligibility_claims` | Süre/eşik gerekçeli hak-reddi | "2 yıl kıdem için yetersiz" (md.14 min 1 yıl), "5 yıl altında tazminat verilmez" (uydurma eşik) | Sıkı: yalnız süre/eşik + red-fiili birleşen cümle; "1 yıl gerekir" gibi doğru bilgilendirme yakalanmaz |
| `fabricated_citation_claims` | İmkânsız mahkeme dairesi | "99. Hukuk Dairesi" (Yargıtay/Danıştay daire sayısı tarihte ~23'ü geçmedi) | `_MAX_CHAMBER = 30` muhafazakâr tavan: gerçek daire (1–~23) asla bloklanmaz |

Bu üç ölümcül hata 2026-05-30'da gerçek Qwen 14B çıktısında yakalanmıştı ("2 yıl minimum süreyi karşılamıyor" — yanlış; "İşçilik Kanunu md.21" — hem uydurma kanun adı hem uydurma madde). Hepsi `tests/agents/test_risk_guard.py` regresyon testiyle bloklanıyor.

Ek olarak `implausible_article_numbers` (madde no > 1100) **ölçüm-amaçlı** bir sinyaldir — veto değil, çünkü bazı vergi/usul kanunlarında yüksek madde numaraları meşrudur.

### 2.4 NLI eşik kalibrasyonu — measure-first disiplini

Verify eşikleri körlemesine değil ölçülerek ayarlanır. `backend/eval/verify_calibration.py` harness'i, `data/eval_benchmark/verify_gold.jsonl` (59 etiketli vaka) üzerinden eşikleri ölçer (commit `fa3c48e`):

- **Tam pipeline F1 = 0.93**; yalnız-fuzzy F1 = 0.64 → NLI, yükü taşıyan katmandır.
- **`NLI_CONTRADICTION_THRESHOLD = 0.70` bu kümede optimal:** contradiction recall 0.80 + **SIFIR yanlış-veto**. 0.50/0.60 yanlış-veto üretir; 0.90 recall'u 0.60'a düşürür.
- Fuzzy çelişkiyi yakalayamaz (contradiction kategorisinde model-free acc = 0.00) → NLI vetosu + VERIFY_STRICT fail-closed yapısal olarak zorunludur.

İkinci, saf-dilbilimsel set (`nli_tr_gold.jsonl`, 28 TR çift; `eval/nli_tr_eval.py`, 2026-06-02) eşiği bağımsız doğruladı: TR 3-sınıf doğruluk %82; 0.70'te **veto yanlış-pozitifi 0/20**. Bulgu: NLI tek başına TR'de çelişki yakalamayı %50-77 oranında kaçırır (sayısal/dünya-bilgisi çelişkilerini — "5 yıl gerekir" vs "1 yıl", "cayma hakkı yok" vs "14 gün var" — neutral der). Ama tam-pipeline R = 1.00 / Acc = 0.95 — çok-katman (risk_guard + fuzzy) bu açığı kapatır. **Eşik İKİ sette de optimal çıktı → değiştirilmedi.** Herhangi bir eşiği değiştirmeden önce bu harness çalıştırılmalı, delta raporlanmalı.

### 2.5 Verdict toplama + debate/Constitutional hakemlik

`_verdict_from_ratio`, iddia oranını ve çelişki sayısını harmanlar:
- `contradictions ≥ floor(n/2) + 1` (süpermajority, minimum 2) → **reject**. Tek bir çelişki Türkçe XNLI paraphrase gürültüsü olabileceğinden tek çelişkiyle reddetmez; "yarıdan fazla" iddia çelişmelidir.
- `supported / n_total ≥ 0.20` → **pass**; aksi halde retry hakkı varsa **retry**, yoksa **reject**.

`debate_node` (`backend/agents/nodes/debate.py`) bu verdict'i alıp Constitutional AI self-critique uygular: `pass` → token tasarrufu için doğrudan onay; `reject` → ekstra LLM çağrısı yapılmadan deterministik ret; `retry` → opt-in (`DEBATE_LLM_ON_RETRY=1`) LLM kritiği. LLM kritiği `score < DEBATE_REJECT_THRESHOLD` (0.30) verirse hard reject'e döner. Retry döngüsü `MAX_RETRY = 3` ile sınırlıdır.

### 2.6 Finalize — doğrulanmamış-iddia filtresi

`finalize_node` (`backend/agents/nodes/finalize.py`) son fail-closed kapıdır ama **kapsam-koruyan**dır: `_filter_to_verified`, doğrulanmamış iddialara karşılık gelen cümleleri taslaktan çıkarır, doğrulanmış içeriği bırakır. Halüsinasyon kullanıcıya gitmez (CLAUDE.md §1), ama tüm cevap reddedilmez — vatandaş doğrulanmış kısımdan yararlanır. Hiç iddia yoksa veya hiçbiri doğrulanmadıysa (`n_verified == 0`) cevap reddedilir. Filtreleme yalnız tek-yönlü substring kullanır (`u in norm`): önceki çift-yönlü kural çok cömertti, yapısal cevapta kısa yan-cümleleri daha uzun unverified iddianın alt-parçası sanıp atıyordu (16-soru testinde 12 cümle düşürülmüştü). Cümle silme sonrası öksüz kalan `[src:]` etiketleri `_remove_orphan_source_tags` ile temizlenir.

### 2.7 Faz-1 halüsinasyon kalkanı — ölçülmüş başarı

Faz-1 (commit `b1837af`, `bf6c3b5`), veto detektörlerine **ölçüm altyapısı** ekledi: `data/eval_benchmark/hallucination_gold.jsonl` (40 etiketli satır) + `eval/hallucination_eval.py` harness, her detektörün precision/recall/F1'ini ve temiz cevapta veto-FP'sini ölçer.

| Metrik | Sonuç |
|--------|-------|
| Veto detektörleri (fabricated law / citation / eligibility) | **P = 1.0 / R = 1.0** |
| Halüsinasyon yakalama oranı | %100 |
| Temiz cevapta yanlış-veto (veto-FP) | **0/16** |
| `unsourced_legal_claims` recall (marker genişletme sonrası) | 0.375 → **1.0** |

Yani veto katmanı gerçek halüsinasyonu kaçırmıyor (recall 1.0) ve temiz cevabı yanlışlıkla reddetmiyor (veto-FP 0). Çalıştırma: `cd backend && uv run python -m eval.hallucination_eval`.

### 2.8 Bu oturum: süre-eşik veto ↔ zengin-format çakışması (regresyon düzeltmesi)

Zengin "avukat-ön-görüşmesi" cevap formatı eklenince (commit `f39e6e2`: Kısa cevap → Durumunuza uygulama → Dayanak → Ne yapmalı → Dikkat → Güven, hedef 240-360 kelime, `DRAFT_MAX_TOKENS=768`) bir **regresyon** ortaya çıktı: yeni "Durumunuza uygulama" ve "Dikkat" bölümleri LLM'i *"X yılın altında → kazanamazsınız"* tipi süre/eşik-gerekçeli hak-reddi üretmeye itiyordu. Bu da `risk_guard.negative_eligibility_claims` detektörünü tetikleyip kıdem tazminatı sorularını fail-closed reddediyordu — yani sıfır-halüsinasyon kalkanı doğru çalışıyordu ama yeni format onu sürekli tetikliyordu.

Çözüm (commit `39241b3`), kalkanı gevşetmek yerine prompt'u düzeltmek oldu — `draft.tr.txt` kural 9/26 güçlendirildi:
- **Olumlu/tarafsız uygula:** Olgular bir şartı açıkça karşılıyorsa olumlu söyle ("5 yıl çalıştığınız için en az 1 yıllık kıdem şartını karşılıyorsunuz, hakkınız doğar").
- **ASLA süre-gerekçeli kesin red:** "X yıldan az olduğu için hak kazanamazsınız / tazminat verilmez" cümlesi yazma (kullanıcı kesin süre verse bile, kaynak bunu açıkça demiyorsa); belirsizse "teyit edin" de.
- **Varsayımsal olumsuz senaryo üretme:** Kullanıcı kendi süresini vermediyse "eğer ... altındaysanız ... kazanamazsınız" türü senaryo kurma.

E2E doğrulama: iki kıdem sorusu da artık `verdict=pass`. Aynı oturumda ilişkili bir prompt-guard düzeltmesi (commit `1f4eb04`): zengin formatta Qwen kanun adını düz-metinde yanlış yazıyordu (TKHK → "Ticaret Kanunu"); citation doğruydu, yalnız prose mislabel. `_DRAFT_SYSTEM` kural 11 ile kanun adı yalnız kaynak başlığındaki (title) gibi kullanılacak şekilde sınırlandı. Bu, doğrulama mimarisinin önemli bir tasarım ilkesini örnekler: **güvenlik kalkanı bir kez ölçülüp doğrulandıktan sonra (P/R=1.0), regresyonu kalkanı zayıflatarak değil üretim katmanını (prompt) düzelterek çözeriz.**

## 3. Bilgi Erişimi (Retrieval / RAG)

Sistemin doğrulanabilir cevap üretebilmesi, ham hukuki kaynakları (kanun maddesi + Yargıtay/Danıştay emsali) sorgu bazında isabetli getiren bir erişim katmanına bağlıdır. Bu katman `backend/retrieval/` altında, Qdrant üzerine kurulu hibrit bir mimaridir ve vatandaş diliyle yazılmış sorgulara göre özel olarak ayarlanmıştır.

### 3.1. Vektör Deposu ve Gömme (Embedding) Modeli

Production koleksiyonu Qdrant'ta `adalet_mursit_hybrid` adıyla tutulur (159.638 nokta). İki ayrı koleksiyon vardır:

| Koleksiyon | Dense | Sparse | Rol |
|------------|-------|--------|-----|
| `adalet` | BGE-M3 (1024-dim) | BGE-M3 | Master kaynak — seed buraya gider |
| `adalet_mursit_hybrid` | Mursit-Base-TR (768-dim) | BGE-M3 | **Production** |

Dense gömme için **`newmindai/Mursit-Base-TR-Retrieval`** (768-dim) kullanılır. Bu Türkçe-hukuk için fine-tune edilmiş model, baz BGE-M3'e kıyasla iki yönlü kazanç sağlar: **kanun@5 metriğinde +7pp** (hukuk maddesi bulma) ve **P95 latansta -42%** (78ms → 46ms, ~10x daha hızlı dense encode). Seed sonrası `sync_mursit_delta.py` ile bu koleksiyon `adalet` master'ından senkron tutulur.

v2 benchmark (186 vaka) ölçümü:

| Metrik | Mursit (prod) | BGE-M3 (referans) |
|--------|---------------|-------------------|
| domain@1 | 79.6% | 81.2% |
| domain@5 | 96.8% | 96.2% |
| kanun@5 | **50.5%** | 43.5% |
| P95 | **46ms** | 78ms |

### 3.2. Hibrit Arama ve Domain-Aware Sparse

Arama dense (Mursit) + sparse (BGE-M3 BM25-benzeri) sinyallerini birleştiren hibrit bir yapıdır (`hybrid_search.py`). Sparse gömme her domainde değil, **yalnızca leksikal eşleşmenin kritik olduğu domainlerde** çalıştırılır: `SPARSE_ENABLED_DOMAINS=vergi,trafik,icra`. Bu domain-aware ikili gömme yaklaşımı (`4050ae2`) vergi domaininde **+36pp** kazanç ve genel **P95 -42%** iyileşmesi getirdi — sparse her yerde açık olmadığı için gereksiz hesap maliyeti ve gürültü ortadan kalktı.

### 3.3. Adaptif Yönlendirme (Adaptive Routing)

HyDE (hipotetik belge gömme) ve Multi-Query (çoklu paraphrase) genişletmelerini **global açmak zarar veriyordu** — bazı domainlerde performansı düşürdüğü A/B ölçümüyle saptandı (`adaptive_router.py`):

- **HyDE kazandığı:** tüketici +12.5pp, kira +14.3pp, vergi +20pp — fakat trafik -20pp, idari -17pp
- **MQ kazandığı:** trafik +20pp, kira +14.3pp — fakat tüketici -18pp, vergi -40pp

`route_query` bu yüzden kararı üç faktöre dayandırır: (1) master switch (env), (2) domain whitelist, (3) sorgu karmaşıklığı. Karmaşıklık skoru sorgu içeriğine göre üretilir — kanun/madde referanslı sorgular (örn. "TKHK m.11") zaten spesifik olduğundan 0.15 alır ve genişletme atlanır; konuşma dili kalıpları ("ne yapabilirim", "hakkım var mı") 0.85 alır ve HyDE tetiklenir. Böylece her sorgu için yalnızca o domain+karmaşıklık çiftinde faydalı strateji seçilir (`hybrid` / `hyde` / `mq` / `hyde+mq`).

### 3.4. Spekülatif Erişim (Latans Üst Sınırı)

Kalite genişletmelerinin (HyDE/MQ) latansı şişirmesini engellemek için spekülatif erişim kullanılır (`speculative_search.py`, `SPECULATIVE_ENABLED=1`, `SPECULATIVE_DEADLINE_S=2.0`):

1. Hybrid arama **hemen** başlar — her zaman bir baseline sonuç garantisi.
2. HyDE/MQ paralel başlar; bunlara wall-clock bütçesi (deadline) tanınır.
3. Bütçe içinde biten advanced görev → kaliteli sonuç; bitmeyen → iptal, hybrid fallback.

Kullanıcı bekleme süresi 46ms–2046ms aralığında, toplam ≈ `max(hybrid_ms, deadline_s)` ile sınırlıdır. Önemli nüans: bu bir **üst sınır**, mutlak "garanti" değil — hybrid'in kendisinin yavaşlaması (Qdrant GC, embedder cold-start) toplamı uzatabilir; bu yüzden `hybrid_ms` ve `advanced_ms` ayrı loglanır (`76cb321` wall-clock bug fix).

### 3.5. Yeniden Sıralama (Reranking) ve Faz-4 Fine-Tune

İlk bulgular cross-encoder reranker'ın (BGE-reranker-v2-m3) **konuşma diliyle yazılmış sorgularda güvenilmez** olduğunu gösterdi: "3 ay önce aldığım buzdolabı bozuldu" gibi vatandaş-dili sorguda tüm adaylara noise-floor (~0.001–0.005) skor veriyor, gerçek hukuki alakayı ayırt edemiyordu. Bu sorun iki katmanda ele alındı:

**(a) Domain-prior tier-sort (kısa vade).** Rerank sonrası `_domain_priority_rerank` stable tier-sort'u (`f6907de`) triaj domaininin birincil kanununu (tüketici → TKHK) tier-0'a alır. Güvenilir domain prior'ı, gürültülü cross-encoder skorunu telafi eder. Bu yüzden bir `RERANK_SCORE_MIN` eşiği işe yaramaz — herhangi bir eşik iyi mevzuatı (TKHK m.11) da silerdi.

**(b) Faz-4 konuşma-dili fine-tuned reranker.** Konuşma dili sentezli TR-hukuk verisiyle özel bir reranker eğitildi (`ff5932b` pipeline, `4b7624f` 12GB GPU OOM düzeltmesi). `RERANKER_MODEL=models/reranker-tr-legal` ile devreye alındı. Held-out validation üzerinde eşikten bağımsız, Qdrant'sız **A/B pairwise** ölçümü (`3b1ed6c`, `eval_ab.py`) baz modele kıyasla net kazanç gösterdi:

| Metrik | Base | Fine-tuned | Δ |
|--------|------|-----------|---|
| Pairwise accuracy | 0.873 | **0.952** | **+7.9pp** |

Ek olarak pozitif/negatif skor **ayrımı ~2x** genişledi — yani fine-tuned model alakalı ve alakasız pasajları çok daha keskin ayırıyor.

### 3.6. Opt-in Gelişmiş Erişim Modülleri

Daha ağır erişim teknikleri offline-build gerektirdiğinden bayrakla kontrol edilir (`backend/.env`): `RAPTOR_ENABLED=1` (hiyerarşik özet ağacı), `GRAPH_RAG_ENABLED=1` (bilgi grafı + online expand), `COLBERT_QUERY_ENABLED=0` (geç-etkileşim sorgu). Kodları `raptor.py`/`raptor_runtime.py`, `graph_rag.py` ve `rerank_provider.py` altında yer alır.

### 3.7. Canlı Çapraz-Doğrulama (yargi-mcp / mevzuat-mcp)

Erişim yalnız yerel corpus'la sınırlı değildir; `yargi_client.py` ve `mevzuat_client.py` üzerinden canlı MCP sunucularına bağlanılarak iddialar orijinal kaynaktan çapraz-doğrulanır. Ölçülmüş kısıtlar:

- **KANUN-by-number güvenilir:** `mevzuat-mcp` KANUN aramasını `mevzuat_no` ile sağlam veriyor; tüm domainlerin kanun katalogu tam seed edildi.
- **YÖNETMELİK düşük recall:** title-search ile tüketici yönetmelikleri (Mesafeli Sözleşmeler, Garanti Belgesi vb.) free MCP'den çekilemiyor.
- **Emsal'de relevance ranking yok:** Public yargi-mcp (Bedesten) gevşek token-match + tarih sıralı sonuç veriyor, alaka sıralaması yapmıyor.

### 3.8. Bilinen Boşluk — Emsal Corpus Hacim Baskısı

Emsal getirme kalitesinin ana sınırı, corpus'un **anayasa biaslı** olmasıdır. Qdrant sayımı: 46.386 anayasa vs 3.825 yargitay vs 4.206 danistay chunk. Önemli bir düzeltme: İş Hukuku Yargıtay kararları corpus'ta **zaten mevcut** (yargitay isHukuku=1871) — sorun veri eksikliği değil, ~9:1 anayasa hacim baskısının hybrid+cross-encoder'ı domine etmesidir. Çözüm olarak emsal node'una **court-priority tier-sort** (`bfd7ffc`, `_court_priority_sort` + `DOMAIN_PREFERRED_COURTS`) eklendi: vatandaş-yardım domainlerinde yargitay/danistay tier-0, anayasa tier-2 — mevzuat domain-tier-sort'unun emsal karşılığı. Yine de tüketici ayıplı-mal gibi spesifik konularda retrieve edilebilir kaliteli Yargıtay emsali kıt; bu, üst-kaynak (free MCP relevance yokluğu) ile sınırlı açık bir boşluktur.

### 3.9. Platform Notu (Windows)

Bu Windows geliştirme makinesinde embedder/reranker yüklemesi, `pyarrow`↔`torch` native import sırasına duyarlılık nedeniyle süreci sessizce çökertiyordu (stdout yutulur, exit 0). Çözüm `core/native_preload.py` (`eb2fca2`): `pyarrow.dataset` en başta import edilir; tüm entry-point'lere bağlıdır ve `DISABLE_PYARROW_PRELOAD=1` ile kapatılabilir (Linux/Docker'da gereksiz). Bu sayede hibrit+rerank retrieval ve eval harness'ları doğrudan bu kutuda GPU üzerinde koşar.

## 4. Dava-Sonucu Tahmini (Faz-5) — Silver Yanılsaması Destanı

Bu bölüm projenin en öğretici dürüstlük hikâyesidir: bir modelin "çalışıyor" diye raporlanıp, titiz değerlendirme altında **rastgelenin altına** düştüğünün ifşa edilmesi ve doğru zeminde gerçekten çalışan bir modele dönüştürülmesi. Tez anlatısı olarak değeri yüksek bir negatif-sonuç-ardından-onarım vakasıdır.

### 4.1 Kurulum — BERT-TR 3-Sınıf Zayıf-Etiketli

8. ajan olan **Tahmin Ajanı** (`agents/nodes/tahmin.py`), getirilen benzer Yargıtay emsallerinden dava sonucunu kestirir. İki katmanlı bir mimari kuruldu (`backend/predictive/inference.py`):

- **Heuristic baseline** (commit `cd92091`): emsal kararların hüküm bölümünden `_classify_outcome` regex'iyle "kabul/ret/kısmen" sinyallerini oylar, tutucu bir tahmin üretir. Sinyal yetersizse dürüstçe `belirsiz` döner.
- **Fine-tuned BERT-TR** (commit `2886586`): 3-sınıf (`kazandi` / `kaybetti` / `kismi`) sınıflandırıcı, `erdem-erdem/Turkish-Law-700k`'dan **zayıf-etiketli** (silver) `data/predictive/labeled_v2.jsonl` (dengeli 6000×3) üzerinde eğitildi; sıcaklık-ölçeklemeyle (`temperature.json`, T=1.56) kalibre edildi.

İlk eğitim raporu (`metrics.json`, silver test-split): **accuracy 0.8256 / f1_macro 0.8249, ECE 0.0303**. Görünürde başarılı bir model.

### 4.2 İlk Boşluk Kapatma — Bağımsız Eval Harness + Train/Serve Hizalama (`3952c4f`)

`metrics.json`'a güvenmek yetmez; iki boşluk kapatıldı:

1. **Bağımsız eval harness** (`predictive/eval_predict.py`): checkpoint'i alıp deterministik test-split üzerinde yeniden ölçer. Sonuç eğitim raporuyla **birebir** (accuracy 0.8256 / f1_macro 0.8249, ECE ≤0.05). Saf çekirdek (`classification_metrics`) torch gerektirmez → hermetik test edilebilir. Kod yorumunda silver "açıkça işaretli" (`--gold` desteği ile).
2. **Train/serve hizalama fix**: kritik bir OOD bug'ı. Model olay+gerekçe karar metniyle eğitilmişti ama canlıda BERT'e kullanıcının çıplak (kısa) sorusu veriliyordu. `_model_predict` artık emsal kararların **hüküm-öncesi** facts'ini kullanır; `_facts_before_hukum` hükmü dışlayarak sızıntısız girdi sağlar.

Bu turda BERT yolu için **+12 test** yazıldı (daha önce BERT yolu hiç test edilmiyordu), 403 test geçti.

### 4.3 Gold Eval Hattı — Hukukçu-Dostu Köprü (`d5f6bc9`, `6a7d19f`, `2bfc589`)

Silver etiketin gerçek tavanı yansıtmadığını ölçmek için bağımsız bir doğrulama hattı kuruldu:

- `scripts/predictive/build_gold_eval.py`: Qwen, **held-out** kararın HÜKÜM fıkrasını okuyup sonucu adjudicate eder (de facto ground truth).
- `gold_review.py`: hukukçu turu için köprü — başta CSV'ydi, okunaksız olduğu için **hukukçu-dostu .xlsx**'e çevrildi (`6a7d19f`).
- `eval_predict --gold-kind human|llm-ref` ile her iki gold türü desteklenir.
- Erken bir hata yakalandı: ilk gold-review etiketi 400-karakterlik `hukum_excerpt` **kesitinden** üretiliyordu; tam hükme geçildi (`2bfc589`).

### 4.4 KRİTİK BULGU — Silver Balonu Patladı (`f055d7b`)

İlk değerlendirmenin tümü hatalı bir kesitten yapılmıştı. Düzeltme: `fetch_full_texts` parquet'ten **tam hükmü** çeker, `extract_full_hukum` (`_DISPOSITION_RE`) temiz hüküm bölümünden başlar; Qwen yeniden koşturuldu (`LLM_SPECULATIVE=0` ile uzun-prompt logits-broadcast çökmesi guard'lı).

Tam-hüküm zemininde ölçülen gerçek, ilk rapordan tamamen kopuktu:

| Ölçüm | Silver (zayıf-etiket) | Tam-hüküm Qwen-ref |
|---|---|---|
| Silver ↔ Qwen uyumu | — | **%29.5** (105/149 çelişir) |
| BERT accuracy | 0.8256 | **0.2817** |
| ECE | 0.0303 | **0.55** |

**0.2817, rastgele tahminin (%33) ALTINDA.** Yani model gerçekte çalışmıyordu; üstelik gerçek sonuca **anti-korele** öğrenmişti.

**Kök sebep:** silver etiketleyen `_classify_outcome` regex'i Yargıtay'ın **onama/bozma** mantığını yanlış okuyor. Davacı lehine **bozma** aslında "kazandı" demektir; ama regex metinde "ret" görüp "kaybetti" etiketliyordu. Model bu hatalı kalıbı sadakatle öğrenmiş → gerçek dünyada ters çalışıyordu. Heuristic baseline de aynı regex'i kullandığı için o da kusurlu.

**Güvenlik kalkanı sayesinde bu hata kullanıcıya hiç ulaşmadı:** tahmin display-only, 0.85-cap'li, verify/debate'i override etmez. Yanlış 0.825 hiçbir zaman hukuki bilgi olarak vatandaşa gitmedi.

### 4.5 Çözüm — Qwen Tam-Hüküm ile Yeniden Etiketle + Yeniden Eğit (`2325dbe`)

İnsan-gold turu iptal edilince (2026-06-02), tam-hüküm Qwen-ref'i de facto ground truth oldu. `scripts/predictive/relabel_qwen.py`:

- `labeled_v2`'nin **train+val** split'inden (seed=42) **2889 vaka**yı seçti — gold_qwen test-split'iyle **çakışmaz** (temiz eval garantisi).
- Her vaka için aynı leak-free girdiyi (olay+gerekçe, hüküm hariç) korurken, Qwen'in TAM HÜKÜM okumasını **doğru etiket** olarak yazdı.
- **0 LLM hatası**, `LLM_SPECULATIVE=0`, incremental flush (uzun koşu çökerse ilerleme korunur), `belirsiz` etiketler 3-sınıf eğitime alınmadı.

Ardından BERT-TR `predictive.train` ile bu doğru etiketlerle yeniden eğitildi. Bağımsız `gold_qwen` held-out üzerinde sonuçlar:

| Metrik | Eski (silver) | Yeni (Qwen-etiket) |
|---|---|---|
| accuracy | 0.28 | **0.7324** |
| f1_macro | 0.27 | **0.70** |
| ECE | 0.55 | **0.029** (kalibre T=1.017) |

Yani silver hatalıydı (onama/bozma); doğru Qwen-etiketle eğitilen model **gerçekten öğrendi**. Model `predictive/checkpoints/best`'te; `PREDICTIVE_USE_MODEL=1` ile inference otomatik kullanır.

### 4.6 Çıktıya Bağlama + Min-Emsal Guard + Dürüst Çerçeveleme (`39241b3`)

Bu oturumda model üretime ve çıktıya bağlandı. Tahmin daha önce `PREDICTIVE_ENABLED=0` (opt-in) olduğu için hiç üretilmiyordu; açılınca iki sorun çıktı, ikisi de düzeltildi:

1. **Zengin-format ↔ risk-veto çakışması (regresyon):** yeni "Durumunuza uygulama" / "Dikkat" bölümleri LLM'i "X yılın altında → kazanamazsınız" gibi süre-gerekçeli hak-reddine itiyordu → `risk_guard` fail-closed reddediyordu (kıdem soruları reject). `draft.tr.txt` (kural 26) güçlendirildi: olguları olumlu/tarafsız uygula ("şartı karşılıyorsunuz" / "teyit edin"), asla süre-gerekçeli kesin red ya da varsayımsal olumsuz senaryo üretme. E2E sonrası iki kıdem sorusu da `verdict=pass`.
2. **BERT yolunda min-emsal guard yoktu:** `_model_predict` tek/zayıf emsalden bile 0.85-cap'li kendinden emin tahmin üretiyordu ("kaybetti %84" gibi) → vatandaşı haklı davadan caydırma riski (kırmızı çizgi). Heuristic'teki `_MIN_SIGNAL=2` guard'ı BERT yoluna da eklendi: <2 kullanılabilir emsal-facts → düşük-güven `belirsiz`. Eski OOD question-fallback kaldırıldı.

Güvenlik invariantları korundu (453 mock test + ruff yeşil):

- **Display-only:** tahmin yalnız `PredictionCard`'da gösterilir, verify/debate hard-gate'ini etkilemez.
- **0.85-cap:** `_MAX_CONFIDENCE = 0.85` — model asla "%100 kazanırsın" demez.
- **Disclaimer + dürüst çerçeveleme:** `PredictionCard` "geçmiş benzer kararlar ALEYHE eğilim" der, "siz kaybedersiniz" demez; belirsizde % gizli; her tahminde hukuki sorumluluk reddi zorunlu.

### 4.7 Tez Anlatısı

Faz-5'in değeri "0.73'lük bir model" değil, **bilimsel dürüstlük döngüsünün** kendisidir: kur → titiz bağımsız eval ile silver-yanılsamasını ifşa et (0.825 sahteydi; tam-hüküm 0.28, rastgelenin altında) → kök-sebebi teşhis et (regex + onama/bozma yanlış-okuması) → LLM tam-hüküm ile yeniden etiketle → 0.73 **çalışan** modele ulaş. Dürüst caveat açıkça kayıtlı: **0.73 Qwen-ref'e karşıdır, insan-gold değil** (hukukçu turu iptal edildi). Bu negatif-sonuç-ve-onarım hikâyesi, güvenlik kalkanının (display-only / cap / override-etmez) neden mimarinin merkezinde durduğunu da kanıtlar — yanlış model bile kullanıcıya zarar veremedi.

**Kaynak:** `backend/predictive/` (`inference.py`, `eval_predict.py`, `train.py`, `calibrate.py`), `backend/scripts/predictive/` (`relabel_qwen.py`, `build_gold_eval.py`, `gold_review.py`); hafıza: `smartening-masterplan` (Faz-5), `tr-legal-training-data`. Commit'ler: `3952c4f`, `d5f6bc9`, `f055d7b`, `2325dbe`, `39241b3`.

## 5. Akıllandırma Fazları (Faz-1..5) ve Değerlendirme

### 5.1. Master-Plan: microGPT Reddi → 5 Gerçek Kaldıraç

Bu çalışma kolu, "ADALET'i nasıl gerçekten akıllandırırız?" sorusuyla başladı. Karpathy'nin microGPT'si (4.192 parametre, karakter-seviye, **öğretici** bir araç) çok-ajan araştırmasıyla incelendi ve **REDDEDİLDİ**: Qwen 14B + BERT-TR üzerine kurulu bir sistemi akıllandırmaz, ürüne girmez. Onun yerine, projenin kendi yol haritasında zaten planlı olan **5 gerçek kaldıraç** efor/etki sırasına göre fazlara bölündü (plan dosyası: `~/.claude/plans/wiggly-spinning-pearl.md`).

| Faz | İş | Efor | Etki | Model eğitimi | Commit |
|-----|----|------|------|---------------|--------|
| 1 | Halüsinasyon kalkanı + ölçüm | Düşük | Yüksek (kırmızı çizgi) | Hayır | `b1837af`, `bf6c3b5` |
| 2 | DistilBERT-TR triaj | Orta | Orta-Yüksek (−4s + doğruluk) | Evet (fine-tune) | `0dfa6a2`, `d221c82` |
| 3 | NLI-TR ölçümü/adaptasyonu | Orta | Orta (verify FP↓) | Eşik/veri | `986ac42` |
| 4 | Türkçe reranker fine-tune | Yüksek | Orta-Yüksek (kaynak kalitesi) | Evet (GPU) | `ff5932b`, `4b7624f`, `3b1ed6c` |
| 5 | BERT-TR predictor + benchmark | Yüksek | Tez + tahmin | Evet (GPU) | `3952c4f`, `2325dbe`, `39241b3` |

> NLI-TR (Faz-3), reranker'dan (Faz-4) öne alındı: daha düşük efor, verify'ı doğrudan etkiler.

Tüm fazlarda kesişen kurallar korundu: **fail-closed verify**, **sahte test verisi**, yasa-fact haritaları yalnızca `mevzuat.gov.tr` / `yargitay.gov.tr`'den teyitli ("asla yasa uydurma"). (v2.3: "lokal model zorunlu" kuralı KALDIRILDI — lokal + bulut hibrit serbest.)

### 5.2. Faz-1 — Halüsinasyon Kalkanı + Ölçüm

**Boşluk:** Süre-uygunluk veto katmanı (`risk_guard.verify_risk_veto`, `verify.py:204`) canlıydı ama (a) detektör precision/recall'ı **hiç ölçülmüyordu**, (b) kapsam dardı (uydurma Yargıtay daire atfı + imkânsız madde no yakalanmıyordu).

Kapatma (commit `b1837af`):
- **Yeni veto detektörü** `fabricated_citation_claims` — imkânsız Yargıtay/Danıştay dairesi (daire no >30).
- **Yeni ölçüm** `implausible_article_numbers` — madde no >1100 (veto değil, yalnızca ölçüm).
- **Gold-set** `data/eval_benchmark/hallucination_gold.jsonl` (40 etiketli satır) + **harness** `eval/hallucination_eval.py` (saf çekirdek, LLM'siz test edilebilir; `quality_gate.py` deseni).

**Ölçülen sonuç:** Veto detektörleri **P=1.0 / R=1.0**, halüsinasyon yakalama **%100**, temiz cevaplarda **veto-FP 0/16** (iyi cevap reddedilmiyor). Açık bulgu: `unsourced_legal_claims` recall'u dardı (0.375); takip commit'inde (`bf6c3b5`) marker genişletmesiyle **0.375 → 1.0**'a çekildi. Bu faz, üç ölümcül gerçek-Qwen hatasını (uydurma "İşçilik Kanunu", uydurma "5 yıl altında tazminat yok" kuralı, "2 yıl minimum karşılamıyor" yanlış-çıkarımı) regresyon testiyle kalıcı olarak bloklar.

### 5.3. Faz-2 — DistilBERT-TR Triaj

**Hedef:** Domain triyajını (8 sivil hukuk alanı) keyword+Qwen yerine fine-tuned küçük sınıflandırıcıya taşımak → LLM yükünü ve P95 gecikmesini (~4s/sorgu) düşürmek.

Yaklaşım (commit `0dfa6a2`, `d221c82`): keyword fast-path → **DistilBERT** (`dbmdz/distilbert-base-turkish-cased` deseni, ~50ms domain) → düşük güvende LLM fallback (`agents/triage_classifier.py`). Model varsa otomatik aktif olur; yoksa `None` döner ve LLM triaj korunur (predictive deseni — graceful degradation). Eğitim verisi: `scripts/triage/gen_data.py` ile **924 sentetik örnek** (`data/triage/`), HF Trainer ile eğitildi ve kalibre edildi. 353 ajan testi yeşil kaldı (regresyonsuz).

### 5.4. Faz-3 — NLI-TR Ölçümü (Measure-First, Eşik Değiştirilmedi)

**Hedef:** mDeBERTa XNLI'nin Türkçe paraphrase'lerde yanlış-pozitif çelişki üretip üretmediğini ölçmek (verify iyi cevabı reddedebilir mi?).

Yaklaşım (commit `986ac42`): İkinci, saf-dilbilimsel set eklendi — `data/eval_benchmark/nli_tr_gold.jsonl` (28 TR çift: 12 entailment / 8 neutral / 8 contradiction) + harness `eval/nli_tr_eval.py` (saf çekirdek + 11 test).

**Kritik bulgu ve karar:** İKİ-set kalibrasyon yapıldı. Production eşiği **0.70 hem yeni TR sette hem otoriter `verify_gold`'da optimal çıktı → eşik DEĞİŞTİRİLMEDİ.** 0.50 küçük sette "bedava" görünüyordu ama otoriter sette yanlış-veto ekliyordu, recall kazandırmıyordu. Ham ölçümler:
- NLI tek başına TR çelişki yakalama yalnızca **%50–77** — sayısal/dünya-bilgisi çelişkilerini kaçırıyor ("5 yıl gerekir" vs "1 yıl", "cayma hakkı yok" vs "14 gün var" → neutral diyor).
- AMA tam pipeline (Faz-1 risk_guard + fuzzy + NLI) **R=1.00 / Acc=0.95** — çok-katmanlı yapı NLI'nin tek başına bıraktığı açığı kapatıyor.

Bu yüzden Faz-3 bir config değişikliği değil; **mimariyi kanıtla doğrulayan ölçümdür** (tez malzemesi). Kalibrasyon harness'ı `eval/verify_calibration.py`, verify eşikleri için referans kalır: NLI_CONTRADICTION 0.70 ölçülmüş-optimal (contradiction recall 0.80 + sıfır yanlış-veto), eşik sezgiyle kaydırılmaz.

### 5.5. Faz-4 — Türkçe Reranker Fine-Tune

**Boşluk:** Cross-encoder konuşma-dili Türkçe'de güvenilmez ("depozito" vs "güvence bedeli"); o ana kadar geçici çözüm domain tier-sort'tu.

Boru hattı (commit `ff5932b`) tamamen kuruldu: `scripts/reranker/` — `load_sources.py` (HF BEIR → çift+corpus), `synth_queries.py` (Qwen few-shot kolokyal soru + embedder consistency filtresi), `mine_negatives.py` (hard-negative madenciliği), `train.py` (CrossEncoderTrainer, warm-start `BAAI/bge-reranker-v2-m3`), `eval_ab.py` (A/B). Veri kaynağı gerçek public BEIR korpusuydu (newmindai caselaw/regulation, CC-BY-4.0). Ceza/aile hukuku scope-filtre ile elendi (kırmızı çizgi korunur).

**Eğitim + A/B sonuçları (RTX 4070):**
- İlk eğitim: 3 epoch, ~9dk40s, train_loss 0.23. OOM dersi: 12GB'da AdamW 568M sığmadı → `optim=adafactor` + `max_length=320` (commit `4b7624f`).
- Geliştirilmiş tur: synth ölçekte (520/600 kabul, %87) → re-mine (train 7168 / val 796) → re-train (eval_loss **0.51 → 0.45**).
- **A/B kazandı** (commit `3b1ed6c`, held-out val): base bge-reranker-v2-m3 vs fine-tuned → **pairwise accuracy 0.873 → 0.952 (+7.9pp)**, ayrım gücü **0.38 → 0.71 (~2×)**.
- Akıl-sağlığı: "depozitomu vermiyor" → ilgili kira **0.976** vs ilgisiz vergi **0.0002**.

Model `models/reranker-tr-legal` (gitignore'da). Üretime bağlama ops adımı: `RERANKER_MODEL=models/reranker-tr-legal`.

### 5.6. Faz-5 — Dava-Sonucu Tahmini (Silver Yanılsaması → Çalışan Model)

Faz-5 BERT-TR 3-sınıf tahmin modeli (kazandı/kaybetti/kısmi, kalibre T) zaten kuruluydu; bu faz onu **sertleştirdi** ve kritik bir kök-sebep buldu. Anlatı bütünüyle "measure-first"in en güçlü kanıtıdır:

1. **Silver-balon ölçümü (commit `3952c4f`, `d5f6bc9`):** Bağımsız eval harness `predictive/eval_predict.py` kuruldu. Model silver test-split'inde **accuracy 0.8256 / f1_macro 0.8249** (metrics.json ile birebir, ECE 0.0303). Sonra GOLD eval hattı (Qwen held-out kararın HÜKÜM'ünü okuyup adjudicate eder) kuruldu.
2. **Balon patladı (commit `f055d7b`, `2bfc589`):** İlk ölçüm 400-char hüküm kesitinden yapılmıştı (hatalı). Tam-hüküm extraction'la düzeltilince: silver↔Qwen uyumu yalnız **%29.5** (rastgele %33'ün ALTINDA); BERT silver'da 0.8256 iken tam-hüküm Qwen-ref'inde **0.2817 (ECE 0.55)**. Kök-sebep: silver `_classify_outcome` regex'i ONAMA/BOZMA'yı yanlış okuyordu (davacı lehine bozma = aslında kazandı; silver "ret" görüp "kaybetti" diyordu) → model bu hatalı kalıbı öğrenmiş, gerçek sonuca **anti-korele** olmuştu. **0.825 tamamen yanılsamaydı.** Güvenlik: tahmin display-only, 0.85-cap, verify'ı override etmez → yanlış çıktı kullanıcıya hukuki bilgi olarak gitmiyordu.
3. **Çözüldü — A yolu çalıştı (commit `2325dbe`):** `relabel_qwen.py` ile 2889 vaka Qwen tam-hüküm ile yeniden etiketlendi (0 LLM hatası, speculative=0) → BERT-TR yeniden eğitildi → bağımsız held-out `gold_qwen` üzerinde **accuracy 0.28 → 0.7324, f1_macro 0.27 → 0.70, ECE 0.55 → 0.029** (kalibre T=1.017). Doğru etiketle model **gerçekten öğrendi**. Tahmin 8. ajan olarak çıktıya bağlandı (commit `39241b3`: veto-uyum + min-emsal guard).

Dürüst caveat: 0.73 **Qwen-ref'e karşıdır** (insan-gold değil; hukukçu turu iptal edildi → Qwen-ref de facto ground truth). Bu, tez için ifşa edilen ve sahiplenilen bir sınırlamadır.

### 5.7. Değerlendirme Harness'ları (Toplu)

Her faz kendi bağımsız ölçüm aracıyla doğrulanır — hiçbir iyileştirme "his" ile kabul edilmez:

| Harness | Yol | Ölçtüğü |
|---------|-----|---------|
| Halüsinasyon | `backend/eval/hallucination_eval.py` | Detektör P/R/F1 + temiz cevapta veto-FP |
| NLI-TR | `backend/eval/nli_tr_eval.py` | TR 3-sınıf çelişki doğruluğu (saf çekirdek) |
| Verify kalibrasyon | `backend/eval/verify_calibration.py` | Eşik optimalliği (FUZZY/LETTUCE/NLI), pipeline F1 |
| Reranker A/B | `backend/scripts/reranker/eval_ab.py` | base vs fine-tuned pairwise accuracy / ayrım |
| Tahmin | `backend/predictive/eval_predict.py` | accuracy / f1_macro / ECE (silver + `--gold`) |
| RAG kalite | `backend/eval/ragas_full.py` | Ragas faithfulness/relevance |
| Gözlemlenebilirlik | `core/observability.py` (Langfuse), `/metrics` (Prometheus) | İz/timing |

Diğer destekleyici harness'lar: `verify_ablation.py` (verify ON/OFF), `quality_gate.py`, `draft_quality.py`, `policy_eval.py`, `domain_audit.py`, `edge_cases.py`. Hedef: **500+ vakalık Türkçe hukuk benchmark** seti (Üye 4 tez teslimi, kurulmakta).

### 5.8. "Measure-First" İlkesinin Tekrar Tekrar Kazanması (Tez Malzemesi)

Master-plan boyunca tek bir disiplin defalarca ödüllendi: **eşik/iddia değiştirmeden önce ölç.**
- **Faz-3:** Küçük set 0.50 eşiğini "bedava" gösterdi; otoriter set bunu çürüttü → eşik korundu, halüsinasyon kaçağı önlendi.
- **Faz-5:** 0.8256'lık görkemli doğruluk, bağımsız tam-hüküm ölçümü olmasaydı tezde "çalışan model" diye sunulacaktı; harness onun **anti-korele bir yanılsama** olduğunu ifşa etti ve gerçek 0.73'lük modele giden yolu açtı.

Her iki vakada da "measure-first" hem hatalı bir kararı önledi hem de kök-sebep analizine zemin hazırladı. Bu, projenin "sıfır halüsinasyon" kırmızı çizgisinin sadece runtime'da değil, **geliştirme metodolojisinde** de uygulandığının kanıtıdır ve doğrudan tez anlatısının omurgasıdır.

## 6. Frontend, Kimlik Doğrulama, Supabase ve Çok-Modluluk

Bu bölüm, ADALET-AGENT'in vatandaşla buluştuğu yüzeyi anlatır: `/sor` sohbet uygulaması, gerçek hesap sistemi, Supabase'e tam geçiş ve çok-modlu giriş/çıkış hattı (OCR, ses, dilekçe). Backend tarafı tüm denetim ve sertleştirmelerin yapıldığı AI çekirdeği iken, bu katman onu "kullanılabilir bir ürün" haline getiren kısımdır.

### 6.1. `/sor` Sohbet Uygulaması — Vite + React, elle CSS

`/sor` arayüzü artık bir prototip değil, gerçek bir uygulamadır: **`frontend/`** dizini **Vite 6 + React 18** (JS/JSX) üzerine kuruludur. Bilinçli bir tercihle **Next.js DEĞİL**, **Tailwind DEĞİL**, **Radix/shadcn DEĞİL** — stiller elle yazılmış CSS dosyalarıyla yönetilir (`styles/auth.css`, `account.css`, `history.css`). Bu, ham HTML/CSS prototipinin görsel kimliğini (beam efekti, 3D-tilt kartlar, aurora arka plan — özgün imzalar) 1:1 korumak içindir. Ham prototip `docs/design/prototype-sor/` altında arşivlenmiştir.

Backend'e bağlantı **SSE (Server-Sent Events)** üzerinden kurulur; üç ana modül köprüyü oluşturur:

| Modül | Görev |
|-------|-------|
| `lib/api.js` | `/ask/stream` SSE okuyucusu (event-bazlı dispatch: `node`/`triage`/`clarify`/`sources`/`drafting`/`verifying`/`timing`/`final`/`error`) + dilekçe indirme + OCR upload + `clearSession` |
| `lib/parseAnswer.js` | `AskResponse` → UI köprüsü (backend yanıt şemasını render edilebilir yapıya çevirir) |
| `hooks/useChat.js` | Key-bazlı faz durum makinesi — SSE race condition'larını key-bazlı patch ile çözer |

Çalıştırma: `cd frontend && pnpm dev` (port `:5173`), Vite dev proxy ile `/ask`, `/api`, `/multimodal`, `/me` yolları FastAPI `:8000`'e yönlendirilir.

### 6.2. 11 Batch UI Cilası — Şeffaflık ve Erişilebilirlik

`/sor` arayüzü, ECC araştırma+denetim ajanlarıyla repo desenleri (vercel/ai-chatbot, assistant-ui, morphic) özgün uyarlanarak 11 batch'lik bir cila döngüsünden geçti (`b6dd05f` → `a85397a`):

- **SSE race düzeltmesi** (key-bazlı patch) + stream'de eksik `store_pdf` (CRITICAL), `has_dilekce`/`disclaimers`/`domain_confidence` taşıma, mesaj-eylem çubuğu, stop butonu.
- **AgentTrace** — `claims` + `debate` ajan-izi şeffaflık paneli (hangi ajanın ne dediği görünür; CLAUDE.md madde 5 "explainability panel" gereksinimini karşılar).
- **PredictionCard** — 8. ajanın (Tahmin) çıktısı: "geçmiş kararlar eğilim gösterir" dürüst çerçevesiyle (asla "siz kaybedersiniz" değil), display-only, 0.85 güven tavanı, disclaimer.
- **a11y / WCAG**: drawer focus-trap + Esc kapatma, `aria-live` bölgeleri, progressbar, touch hedefleri ≥44px.
- **Kaynak mührü**: KANUN / YARGITAY için lokal SVG rozetleri (Google favicon API kasıtlı kullanılmadı) + zengin citation popover (✓ doğrulandı + host).
- **`?preview=1` demo modu** (`lib/demoTurn.js`): backend olmadan tüm UI'yı gösteren jüri demosu — production'da `import.meta.env.DEV` ile guard'lı (prod bypass kapalı).
- **PWA** + **inline markdown** (RunText içinde asterisk-tabanlı `**kalın**`/`*italik*`, XSS-güvenli React elemanları).
- **Güvenlik konsolidasyonu (Batch-8)**: `RiskWarning`'den `dangerouslySetInnerHTML` KALDIRILDI (`renderInline`), dilekçe filename sanitize + `encodeURIComponent`, `retryLast` stale-closure düzeltmesi, abort race guard.

### 6.3. Hesap, Profil ve Kalıcı Sohbet Geçmişi (Full-Stack)

Sidebar'daki kullanıcı pill'i, ChatGPT'nin "Plus'a yükselt" mantığı yerine ADALET'e özgü bir menü açar (`UserMenu.jsx` + `accountPanels.jsx`) — 8 panel: nasıl çalışır (7-ajan), kapsam (8 alan + ceza/aile kapsam-dışı dürüstlüğü), kaynaklar, gizlilik & verilerim, erişilebilirlik & tercihler (yazı boyutu, hareketi-azalt, yüksek-kontrast, tercih edilen alanlar), sorumluluk reddi, açık kaynak, profil.

**Kalıcı sohbet geçmişi** tam çalışır: sidebar gerçek geçmiş listesi gösterir (tıkla→yükle, sil), `useConversations.js` ile yönetilir. Geçmiş artık silinmez — `useChat.reset()` yeni sohbet açar ama geçmişi korur; `loadConversation` ile eski sohbet yüklenir.

> **KVKK politika değişikliği (v2.1/v2.2):** "Hiçbir şey saklanmaz" kırmızı çizgisi KALDIRILDI. ADALET normal bir ürün gibi kalıcı geçmiş + hesap tutar; KVKK "blokör" değil "arka plan hijyeni" olarak ele alınır. KORUNANLAR: hukuki sorumluluk reddi (Avukatlık Kanunu yükümlülüğü, asla kaldırılmaz), OCR PII maskeleme (ürün artısı), lokal model (tez direği).

### 6.4. Kimlik Doğrulama — E-posta/Şifre Giriş-Kayıt, Misafir Kaldırıldı

Önce minimal-deps bir öz hesap sistemi kuruldu (stdlib pbkdf2_sha256 600k, bcrypt yok; `POST /auth/register` + `/auth/login`, generic-401 + dummy-hash timing eşitleme, JWT alg-whitelist). Frontend `useAuth.js` + editorial split-screen `pages/AuthPage.jsx` ile gate'lendi.

Sonrasında **misafir modu tamamen kaldırıldı** (`bb7cc00`): site artık **kayıt/giriş zorunlu**dur. `useAuth`'tan `guest`/`continueAsGuest`/`GUEST_KEY` silindi; `Root.jsx` `!authed → AuthPage`'e yönlendirir, AuthPage'de misafir butonu yok. Bu, Playwright E2E testlerini kırdı ve `a425d16` ile onarıldı.

### 6.5. Supabase'e Tam Geçiş (v2.2)

Auth + ilişkisel veri (kullanıcılar, `conversations`, `messages`, `profiles`, `uploaded_files`) artık **Supabase** (hosted Postgres + GoTrue + RLS) üzerindedir. AI çekirdeği (FastAPI + LangGraph + lokal LLM + Qdrant) self-hosted kalır; Supabase yalnız auth + relational katmandır. Tercih nedeni: **gelecekteki şema değişikliklerinin otomatik/sürdürülebilir** olması.

- **Phase A** (`42a06ba`): `useAuth` → Supabase GoTrue (e-posta/şifre + Google + o zamanki misafir).
- **Phase B** (`e2acd30`): `lib/supabaseData.js` (CRUD + RLS); `useConversations`/`usePrefs`/`App.jsx` Supabase'e bağlandı; `api.js`'ten ölü `/me/*` + register/login temizlendi. `conversations.id = TEXT` (backend `uuid4().hex` ile birebir eşleşme için — uuid tipi dashed'e çevirip session eşleşmesini bozuyordu).
- **DB sertleştirme (1. tur, `9615f42`):** RLS `(select auth.uid())` per-query; `save_conversation()` RPC atomik; FK CASCADE; CHECK constraint'ler; `updated_at` trigger; `handle_new_user` `search_path=''`; UNIQUE(conv,turn); **SIGNED_OUT'ta yerel temizleme** (paylaşılan cihaz sızması — CRITICAL bug'dı).
- **DB derin denetim (2. tur, `450cf93`):** RPC sahiplik fail-fast, payload limiti (200 satır/1MB), boyut CHECK'leri, `confidence numeric(5,2)`, MIGRATION GUARD (veri varken yıkıcı re-run DURUR), `docs/DB_OPERATIONS.md` runbook.

Şema canlıda doğrulandı: 4 tablo HTTP 200, `save_conversation` RPC anon çağrıda `42501` RLS-blok (IDOR'a kapalı). `api.js`'in `authHeaders()` fonksiyonu Supabase token'ını (`sb-<ref>-auth-token`) zaten gönderir. **Kalan iş — Phase C:** backend `authenticate`'in Supabase JWT'sini ES256/JWKS ile doğrulaması (`bf57030`'da HS256 secret yanlış olduğu için ES256/JWKS'e geçildi) — yalnız prod `AUTH_ENABLED=1` için gerekli, dev'de default `0`.

### 6.6. Frontend Test Altyapısı

Önceden frontend'de **sıfır** test vardı (backend ~930). Şimdi:

- **Vitest + jsdom**: 125 birim/bileşen/hook testi (16 dosya); `conversationUtils.js`, `usePrefs.sanitize`, `useAuth.userFromToken` test için export'landı.
- **Playwright E2E**: gerçek Chromium'da backend'siz akışlar (`auth.spec.js`, `account-menu.spec.js`, `history.spec.js`) — giriş-kapısı, hesap menüsü, geçmiş.
- **Kapsam** (`@vitest/coverage-v8`) + **`frontend-ci.yml`** (vitest + coverage + build + e2e job'ları; Node 22 — pnpm 11.5 `node:sqlite` için ≥22.13 zorunlu).

Komutlar: `pnpm test` / `test:coverage` / `e2e`. Rehber: `frontend/TESTING.md`.

### 6.7. Çok-Modluluk — OCR, Ses, Dilekçe

Çok-modlu hat `backend/multimodal/` altında üç modülde gerçek modellerle çalışır (Sprint-6'da entegre, 5/5 entegrasyon testi geçti):

| Yetenek | Motor | Detay |
|---------|-------|-------|
| **OCR** | Tesseract 5.4 (TR) + opsiyonel **Qwen2-VL** fallback | `ocr.py`: iki seviyeli — Tesseract zayıfsa (< 50 char) auto-fallback Qwen-VL (`OCR_QWEN_VL_ENABLED=1` opt-in, `lru_cache(1)` ile OOM guard); proje-lokal `tessdata`; decompression-bomb guard (50M piksel); magic-byte doğrulaması (client MIME header'a güvenmez) |
| **STT** | faster-whisper-small (462MB, INT8 CPU) | `stt.py`: WAV/MP3/OGG/FLAC/M4A/WebM magic-byte doğrulaması; `STT_MODEL=large-v3` ile %15 daha doğru |
| **TTS** | Piper `tr_TR-dfki-medium` (61MB ONNX), opsiyonel Coqui XTTS-v2 | `tts.py`: yanıt sesli okuma; `strip_disclaimer` ile hukuki uyarı ses çıktısından kesilir |

**PII maskeleme** (`api/pii.py`) ürün özelliği olarak korunur: TCKN (11 hane, checksum kasıtlı YOK → sahte test verisi de maskelensin diye over-mask fail-safe), telefon, e-posta, IBAN, plaka regex'leri. OCR endpoint'inde çıkarılan metin **bozulmaz** (kullanıcı kendi belgesi, soru için tam metne ihtiyaç var) ama PII tespit sayıları (`pii_detected`, `pii_counts`) frontend'e döner ve kullanıcıyı uyarır. `fingerprint()` (SHA-256 truncated) e-posta/sub gibi kimlikleri loglara ham yazmadan gruplanabilir hale getirir.

**Dilekçe çıktısı** çift formatta üretilir: `agents/dilekce/renderer.py` Jinja2 ile `DilekceContext` → markdown (deterministik, LLM yok) → reportlab **PDF** (Helvetica WinAnsi ile Türkçe ç/ş/ğ/İ desteği) + editlenebilir **DOCX** (vatandaş/avukat düzenler). İndirme endpoint'leri (`api/routes/dilekce.py`) auth + ownership zorunlu (IDOR koruması), UUID4 regex (path traversal), 15 dk cache TTL, ASCII-only Content-Disposition filename.

### 6.8. Zengin Avukat-Ön-Görüşmesi Cevap Formatı

Bu oturumda LLM cevap formatı, kısa-yapısal'dan **avukat-ön-görüşmesi** tonuna yükseltildi (`f39e6e2`, `1f4eb04`, `39241b3`): Kısa cevap → Durumuna uygulama → Dayanak → Ne yapmalı → Dikkat → Güven (240–360 kelime, `DRAFT_MAX_TOKENS=768`). Bu format başlangıçta `risk_guard`'ın süre/eşik veto'sunu tetikledi (kıdem soruları reject ediliyordu); prompt veto-uyumlandı (olumlu/tarafsız uygula, asla süre-gerekçeli kesin red). Ayrıca **kanun-adı guard'ı** eklendi (Qwen TKHK'yi "Ticaret Kanunu" diyordu → düzeltildi) ve tahmin için **BERT min-emsal guard** (`_MIN_SIGNAL=2`; tek emsalden "kaybetti %84" yanıltıcı çıkarımı engellendi).

**Kaçınılanlar (bilinçli kimlik kararları):** streamdown/Shiki/KaTeX, framer-motion, Radix/Tailwind, Google favicon API, `dangerouslySetInnerHTML`, feedback'i kişisel veriyle loglama. Mevcut beam + 3D-tilt + aurora özgün imzalardır ve korunur.

---

İlgili dosyalar (mutlak yollar): `c:\Users\cemmo\Desktop\Ders\adalet-agent\frontend\src\lib\api.js`, `frontend\src\lib\supabaseData.js`, `frontend\src\hooks\useChat.js`, `frontend\src\pages\AuthPage.jsx`, `backend\multimodal\ocr.py`, `backend\multimodal\stt.py`, `backend\multimodal\tts.py`, `backend\api\pii.py`, `backend\api\routes\multimodal.py`, `backend\api\routes\dilekce.py`, `backend\agents\dilekce\renderer.py`.

## 7. Güvenlik, Gözlemlenebilirlik, Deployment ve Bilinen Boşluklar

Bu bölüm, sistemin üretim olgunluğunu üç eksende belgeler: saldırı yüzeyini daraltan güvenlik sertleştirmeleri, kör uçmayı önleyen gözlemlenebilirlik katmanı ve tek komutla ayağa kalkan deployment mimarisi. Tamamlayıcı olarak, sürecin sonunda hâlâ açık olan dürüst boşluklar/backlog kalemleri listelenir — bunlar gizlenmez, çünkü bir doğrulama-odaklı hukuk asistanında "neyi henüz garanti edemiyoruz" sorusu en az "neyi yapabiliyoruz" kadar kritiktir.

### 7.1 Güvenlik Sertleştirme

Backend, art arda iki çok-ajanlı güvenlik denetiminden geçti. Bunlardan ilki 6-ajanlık bir floнun (`architect`, `security-reviewer`, `fastapi-reviewer`, `silent-failure-hunter`, `python-reviewer`, `performance-optimizer`) `backend/` üzerinde yürüttüğü ve 24 iterasyonluk bir `/loop` ile temizlenen kademeli sertleştirme turuydu. İkincisi ise 24-ajanlık, **adversaryal doğrulamalı** bir güvenlik workflow'uydu: bu workflow yalancı-pozitifleri (örneğin "anon key public-by-design" ve "SQL/shell injection YOK" iddiaları) elemiş, geriye kalan 13 gerçek açığı `5b82956` commit'inde düzeltmiştir.

Başlıca sertleştirmeler:

| Alan | Önlem | Commit |
|------|-------|--------|
| **Prompt injection (stored)** | `sanitize.py` delimiter pattern'leri (`KONUŞMA BAĞLAMI`/`<<<SORU>>>`/`[Talimat]`/`confidence=`/`domain=`) + **NFKC normalize** + **zero-width strip** (homoglyph bypass); triaj `_format_history` oturum içeriğini `strip_injection_delimiters`'tan geçirir | `5b82956` |
| **Supabase JWT auth** | `decode_token` GoTrue token'ını doğrular; başlangıçtaki HS256 paylaşımlı-secret yaklaşımı **YANLIŞTI** — kullanıcının projesi modern **ES256 (asimetrik)** kullanıyor. `bf57030` ile **JWKS endpoint'ten public ES256/RS256 anahtarı çekme** (PyJWKClient, in-memory cache, paylaşılan secret YOK) + legacy HS256 fallback; `aud='authenticated'` | `5b82956` → `bf57030` |
| **Fail-secure auth default** | `AUTH_ENABLED` default `'0'`→`'1'`: set edilmezse artık korumasız değil. `ENV=production` + `AUTH_ENABLED!=1` → startup **ÇÖKER** (fail-fast) | `5b82956` |
| **Rate-limit** | `slowapi` ile multimodal endpoint'leri (OCR/STT/TTS: 5/5/10 per-dakika) + invite endpoint (5/saat) DoS guard'ı | `5b82956`, `16ef9f8` |
| **CSP / HSTS / header'lar** | Frontend `vercel.json` (CSP + HSTS + X-Frame-Options + nosniff + Referrer/Permissions-Policy, prod-only, Vite dev'i kırmaz); Caddy katmanında HSTS `max-age=31536000; includeSubDomains; preload` | `5b82956` |
| **Citation URL whitelist** | `CitationSchema` URL'sini `.gov.tr` domain'lerine (mevzuat/yargitay/danistay/resmigazete/adalet/uyap) sınırlar; `javascript:`/`data:`/suffix-confusion düşer → zehirli payload phishing guard | `5b82956` |
| **PIL decompression-bomb** | `Image.MAX_IMAGE_PIXELS=50M` (ocr.py) | `5b82956` |
| **E2E bypass guard** | `?e2e=1` auth-atlama yalnız **localhost** (`localhost`/`127.0.0.1`/`::1`) hostname'inde çalışır — `VITE_E2E=1` build yanlışlıkla staging/preview'e yüklenirse prod'da auth atlamaz; Playwright zaten localhost olduğu için testler etkilenmez | `c0262cc` |

Bunlara ek olarak iteratif sertleştirme turunda: API-key eşleştirmesi `hmac.compare_digest` (timing-safe), exception/info-disclosure sızıntılarının kapatılması (pipeline/multimodal hata stringleri jenerik, tam exception yalnız log'a), log redaksiyonunun liste+iç-içe dict'e kadar recursive PII maskelemesi, ve `VERIFY_STRICT` ile doğrulayıcı çökünce cevabın sessizce geçmek yerine **reddedilmesi** (fail-closed) yer alır.

### 7.2 Veritabanı Derin-Denetimi

Supabase ilişkisel katmanı (auth + `conversations`/`messages`/`profiles`/`uploaded_files`) iki tur 3-ajanlık denetimden geçti (`9615f42`, `450cf93`):

- **IDOR'a kapalı, owner-scoped erişim:** Tüm RLS policy'leri `auth.uid()` → `(select auth.uid())` (per-row yerine per-query, Supabase initPlan optimizasyonu). `save_conversation()` RPC'sinde **sahiplik fail-fast**: başka kullanıcının id'sine yazma artık sessiz no-op değil, açık `forbidden` hatası döner. REST ile doğrulandı: anon çağrı `42501` RLS-blok (SECURITY INVOKER + RLS doğru çalışıyor).
- **Atomiklik:** `save_conversation` RPC conversation upsert + mesaj replace'i **tek transaction**'da yapar → delete/insert arası hatada mesaj kaybı yok.
- **Payload/boyut limitleri:** max 200 satır/1MB payload; `content≤100k`, `citations≤100`, `title≤500`, `confidence numeric(5,2)` CHECK'leri (disk şişirme vektörü kapandı).
- **Fingerprint anahtarlama:** E-posta/PII, log ve `feedback_id`'de `pii.fingerprint()` (sha256 trunc) ile saklanır; tam `sub` yalnız yanıt gövdesinde kalır (`10fd177`).
- **Migration guard:** Veri varken yıkıcı re-run **DURUR** (kazara prod veri kaybı önlenir); paylaşılan cihazda `SIGNED_OUT`'ta yerel veri temizlenir (CRITICAL sızıntı bug'ı düzeltildi).

Operasyonel kararlar `docs/DB_OPERATIONS.md` runbook'unda belgelenir (yedekleme/PITR, hesap-silme Edge Function, eşzamanlılık limiti, pooler, retention).

### 7.3 Gözlemlenebilirlik

Tasarım ilkesi: **"P95/P99 trendi görünmezse kör uçarız."** Gözlemlenebilirlik dış altyapı zorunluluğu olmadan çalışacak şekilde kuruldu.

- **In-process rolling percentile aggregator** (`core/metrics.py`): son 500 örnek üzerinden bounded-deque P50/P95/P99. **Tek-tap mimarisi** — `core/logging._metrics_tap` structlog processor'ı (redaksiyondan ÖNCE) JSON log'dan geçen her timing event'ini otomatik aggregator'a besler. Tek tap noktası sayesinde streaming `/ask/stream` + non-streaming `/ask` + script koşumları dahil HER yol metriğe katkı verir, manuel enstrümantasyon yok (`3137507`, `324f525`).
- **İki endpoint:** `/metrics/latency` (JSON, dış scraper gerektirmez) + `GET /metrics` (Prometheus text exposition format, **bağımlılıksız** `render_prometheus()` — `prometheus_client` gerekmez; quantile-etiketli gauge'lar) (`d569f27`).
- **Langfuse opsiyonel** trace olarak konumlandı; runbook'u `docs/runbooks/langfuse-setup.md`'de.
- **Quality-gate prompt kapısı** (`c317290`): prompt değişikliğinden ÖNCE çalışan 6-kriterli saf-mantık (LLM'siz) scorecard — `length_in_target`, `has_short_answer` korunması, truncation yokluğu, `src_coverage` korunması, unsupported artmaması, P95 regresyon tavanı (×1.20). Kullanıcı direktifi: "prompt'u uzat deme, önce eval kapısı koy."

**Canlı pipeline kırılımı** (gerçek sorgular, `d569f27` ölçümü): `llm.generation` P50=2.9s / P95=32.9s, `verify(NLI)` P50=574ms / P95=6s, `retrieval` P50=2s, `finalize` ~0ms. Soğuk-start tek başına P99'u onlarca saniye şişiriyor (ilk sorgu 38802ms → ikinci 7966ms) — bu, P95/P99 görünürlüğünün somut gerekçesi oldu.

### 7.4 KVKK Politika Değişikliği (v2.2)

v2.2 ile **KVKK artık bir geliştirme kısıtı / kırmızı-çizgi DEĞİL.** ADALET normal bir ürün gibi davranır: sohbet geçmişi, hesaplar ve tercihler standart şekilde saklanır (kayıtlı kullanıcı: Supabase tabloları; misafir modu kaldırıldıktan sonra → kayıt/giriş zorunlu). Bu önceki "KVKK her şeyi sürdürür" çerçevesinden bilinçli bir kopuştur.

Politika değişse de **üç şey korundu** — ama artık KVKK yükü olarak değil, ürün/tez ARTISI olarak:

1. **Belge PII maskeleme** (TCKN/telefon/IBAN) — jüri "wow" + kullanıcı koruması.
2. **Lokal + bulut hibrit** (v2.3: lokal-only zorunluluğu kaldırıldı) — tam-lokal gizlilik/offline modu hâlâ bir artı; en iyi kalite için bulut API'ler serbest.
3. **Hukuki sorumluluk reddi** her yanıtta — bu KVKK değil, AYRI yasal yükümlülük (Avukatlık Kanunu); asla kaldırılmaz.

Not: Kod tabanındaki bazı yorumlar (Caddyfile, docker-compose, `d569f27`) hâlâ KVKK gerekçesiyle (örn. "Langfuse cloud soru içeriğini yurt dışına gönderir") yazılmış durumda; bu, mimari tercihlerin (self-hosted Prometheus, internal-only DB) yan faydası olarak okunmalıdır, blokör olarak değil.

### 7.5 Deployment

Hedef mimari hibrittir: **AI çekirdeği self-hosted** (FastAPI + LangGraph + lokal LLM + Qdrant), **auth + ilişkisel veri Supabase** (hosted Postgres + GoTrue + RLS).

- **Tek-komut production stack** (`0d57a7b`): `docker compose --profile production up -d` ile Caddy (TLS) + llama-server (GPU) + backend + Qdrant + Redis + Postgres birlikte ayağa kalkar.
- **Caddy auto-TLS** (`infra/Caddyfile`): Let's Encrypt ACME ile otomatik HTTPS, HTTP/1+H2+H3, admin API kapalı (reverse-proxy hijack guard), SSE stream için `flush_interval -1`, slowloris'e karşı dial/read timeout ayrımı, JSON access log.
- **Container hardening** (docker-compose): backend `read_only` fs + `cap_drop ALL` + `no-new-privileges` + tmpfs `/tmp`; Redis `requirepass` + AOF; Qdrant API key; tüm servisler `adalet-net` internal'da, host'a expose yok (yalnız backend `127.0.0.1:8000`); resource limit'leri DoS guard. Production default'ları fail-closed: `VERIFY_STRICT=1`, `AUTH_ENABLED=1`, `LLM_MODE=llamacpp_server` (bulut LLM yok).
- **Frontend:** Vercel (CSP/HSTS header'ları `vercel.json`'da, prod-only).
- **Keep-alive workflow** (`5797f0e`): Supabase Free-plan'in 7-gün inaktivite PAUSE'unu önlemek için günlük cron `conversations` tablosuna gerçek DB sorgusu atar (RLS boş `[]` döner ama Postgres'te çalışır → sayaç sıfırlanır); proje ulaşılamazsa job kırmızıya döner (erken haber).

**Token bütçesi kararı** (`324f525`): Kullanıcının "240 default yap VEYA 320 dokümante et" tercihinde **320 bilinçli korundu**. 240 token P95'i ~%23 düşürür AMA yanlış yöndür: hedef-uzunluk cevap (160-220 kelime) ~350-450 token tutar; 240 hedefin ALTINDA kapatır → kısalık sorununu kalıcılaştırır. Doğru yön cap'i ~400'e çıkarmak + prompt'u uzatmaktır. Latans-öncelikli dağıtım `LLM_MAX_TOKENS=240` ile override edebilir.

### 7.6 Bilinen Boşluklar ve Backlog (Dürüst Liste)

| Boşluk | Açıklama | Durum |
|--------|----------|-------|
| **Risk-veto TRUE↔FABRİKE eşik** | Süre-uygunluk halüsinasyonu: sistem "2 yıl kıdem için yetersiz" gibi yanlış-çıkarım üretebiliyor; verify/NLI bunu yakalamıyor çünkü risk-veto, gerçekten doğru bir red ile fabrike edilmiş bir reddi eşik düzeyinde ayırt edemiyor. `answer_risk` detektörlerinin verify'a entegrasyonu öncelikli backlog | Açık (öncelikli) |
| **`AUTH_ENABLED` default** | Dev/test'te default `0` (backend bearer'ı yok sayar, regresyon yok). Prod'da compose `1` zorlar ve `ENV=production`'da fail-fast çöker — ama deployment kararı kullanıcıya bırakılmış, otomatik flip yapılmıyor | Tasarım kararı / dikkat |
| **Emsal corpus eksik** | Emsal corpus'un ~%75'i anayasa ağırlıklı; Yargıtay tüketici kararları eksik. Retrieval kalitesi bu eksiklikten etkileniyor | Açık |
| **`0.73` Qwen-ref insan-gold değil** | Tahmin/eval metriklerinin referansı Qwen-tam-hüküm etiketlemesi; **insan hukukçu gold-standard değil**. Sayı kıyas için anlamlı ama mutlak doğruluk iddiası değil | Metodolojik sınır |
| **Token bütçesi yarım çözüm** | 320 korundu ama "doğru yön" (~400 cap + prompt uzatma + quality-gate'ten geçirme) henüz uygulanmadı | Backlog |
| **In-process metrik tek-worker** | Rolling percentile'lar her uvicorn worker'ı için ayrı; multi-worker'da her worker ayrı snapshot verir (Prometheus federation/agregasyon gerekir) | Ölçek sınırı |
| **LangGraph checkpointer yok** | Persistence/resume için AsyncRedisSaver henüz entegre değil; graph timeout var ama failure-rate/half-open circuit-breaker yok | Mimari backlog |

Bu boşlukların bilinçli ve belgeli olması, sistemin "sıfır halüsinasyon" iddiasını dürüst tutar: garanti edemediğimiz yerlerde sistem ya `[DOĞRULA: ...]` placeholder bırakır, ya cevabı reddeder, ya da "bir avukata danışın" der.
