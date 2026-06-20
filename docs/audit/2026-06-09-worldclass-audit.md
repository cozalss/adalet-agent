# ADALET-AGENT — Dünya-Standardı Tam-Sistem Denetimi (2026-06-09)

> [!IMPORTANT]
> Bu belge 2026-06-09 tarihli denetim snapshot'ıdır. Bazı bulgular sonraki
> çalışmalarda giderilmiş veya dokümantasyonla netleştirilmiş olabilir. Güncel
> durum ve doğrulama kapıları için [`../CURRENT_STATUS.md`](../CURRENT_STATUS.md)
> esas alınır.

> Kaynak: workflow `wf_b4c0f5ba-5f1` — 11 uzman denetim merceği + 5 SOTA araştırma ajanı → adversarial doğrulama → sentez.
> 55 ajan, ~2.7M token, ~640 sn. İstatistik: 99 ham bulgu, 25 doğrulanmış CRITICAL/HIGH, 13 elendi (yanlış-poz/zaten-tasarım), 61 MEDIUM/LOW.

## Yönetici Özeti

ADALET-AGENT'ın teknik çekirdeği (8 ajan, 4-katman verify, ~1300 test, ölçülmüş hybrid+ColBERT RAG, kalibre tahmin modeli) zaten jüri-üstü ve olgun. Bu denetim, "daha fazla backend" değil dünya-standardı kaldıraçlarını sentezler: (1) KANIT/BİLİMSEL TİTİZLİK boşlukları en yüksek risk — halüsinasyon scorecard'ı circular (gold-set onu ölçen detektörlerle kurgulanmış, P=1.0/R=1.0 tautolojik), README/paper/tez arası LLM modeli çelişkisi (9B vs 14B) reproducibility'yi çürütür, kalibrasyon val-set double-dip ECE iddiasını sakatlar; bunlar hakem tarafından anında diskalifiye gerekçesi olur. (2) İKİ KIRMIZI-ÇİZGİ/GÜVENLİK bulgusu doğrulandı ve tek-satır: reject path'inde DisclaimerBar eksik (Avukatlık Kanunu ihlali, App.jsx:648 kodda teyit edildi) ve MCP retry_after sınırsız asyncio.sleep DoS (yargi_client.py:312 teyit). (3) SOMUT PERF KANITI: production filtreleri doc_type/kanun_kodu/madde_no üzerinde çalışıyor (hybrid_search.py:444, hyde.py:124) ama bu field'lar için payload index YOK — sadece domain+source indexli; 159K chunk'ta her filtreli sorgu brute-force, "lokal/hızlı" tez direğinin doğrudan darboğazı. (4) SUNUM/ROI: sesli mod backend hazır ama frontend köprüsü yok (Üye-2 tezinin yüzü), paper-draft hâlâ placeholder-iskelet (kanıt var, taşıma işi). Çoğu yüksek-değerli düzeltme bu Windows kutusunda GPU/Qdrant/API-key OLMADAN yapılabilir.

## Dünya-Standardı Değerlendirmesi

Sistem mühendislik kalitesi açısından çoktan SOTA-komşu: TurkColBERT/Mursit ekosistemini erkenden benimsemiş (stored-ColBERT rerank deployable), fail-closed verify, 4-katman grounding, deterministik policy katmanı — bunların hiçbiri rakip vatandaş-hukuk asistanlarında yok. "Dünyanın en iyisi" eşiğinin altında kalınan yer kod DEĞİL, KANITIN SUNUMU ve SAVUNULABİLİRLİĞİ. En büyük 3 kaldıraç: (A) BİLİMSEL SAVUNULABİLİRLİK — halüsinasyon kalkanının circular-benchmark'ı held-out + insan-gold (Cohen κ) ile gerçek-recall'a dönüştürülmeli; bu yapılmazsa "SIFIR HALÜSİNASYON" başlık-iddiası bir RAG hakeminin ilk hedefi olur. (B) TEK-DOĞRU-KAYNAK TUTARLILIĞI — model adı (9B vs 14B), test sayısı (1313), gold-set sayıları (31/59/24.5k), eşikler (fuzzy 0.45 vs 0.55), ajan sayısı (7 vs 8) dokümanlar arası çelişiyor; açık-kaynak repo jürinin kendi vaadi olduğundan bu tutarsızlık doğrudan güven çöküşü. (C) DEMO-YÜZÜ — sesli mod köprüsü + canlı prod URL topolojisi + jüri demo runbook'u; backend ödendiği halde sunum yüzeyi eksik kaldığı için yüksek ROI. Dürüst kapsam-sınırı (ceza/aile dışı, opt-in özellikler "ölçülmedi" işaretli) projenin EN güçlü farkı — dokümanların kendisi bu dürüstlüğü ihlal etmemeli.

## Hemen Yapılabilir İlk 5 (sıralı)

1. Reject path'e DisclaimerBar ekle (App.jsx:648 — KIRMIZI ÇİZGİ, kodda teyit edildi, tek satır) ve aynı dosyada smalltalk/clarify path'lerini kontrol et
2. Production filtre field'larına payload index ekle: ensure_collection + rebuild_mursit_hybrid.py + seed scriptlerine doc_type/kanun_kodu(KEYWORD)+madde_no(INTEGER) create_payload_index; mevcut koleksiyon için tek-seferlik migration script yaz
3. MCP retry_after sleep'ine üst sınır koy (yargi_client.py:312 — MAX_RETRY_AFTER_S=60 ile min(), DoS açığı, tek satır)
4. README/paper/tez arası LLM model çelişkisini gider: gerçek HF adını doğrula ('Qwen3.5' muhtemelen yanlış), tek üretim-modeli string'i belirle, tüm dokümanlara yay + manşet-sayıların hangi modelle alındığını dipnotla
5. paper-draft.md §4'ü measured-results+ablation+scorecard'taki gerçek değerlerle doldur (placeholder X.XX'leri ölç-değerlerle, 7→8 ajan, fuzzy 0.55→0.45, corpus→159k, benchmark→186) + baseline halüsinasyon-oranı karşılaştırması ekle

## Tam Backlog (40 madde)

### #1 — Reject path'te DisclaimerBar eksik — Avukatlık Kanunu kırmızı-çizgi ihlali
- **Önem/Efor/Durum:** HIGH / S / HEMEN
- **Alt sistem:** frontend (React/Vite — src/)
- **Neden önemli:** KIRMIZI ÇİZGİ ihlali, kodda teyit edildi (App.jsx:648 sadece RejectCard render ediyor, DisclaimerBar yok). Her yanıtta hukuki disclaimer zorunlu (CLAUDE.md §2). Tek-satır fix ama TÜBİTAK/Teknofest/üniversite jürisinin uyum açığı olarak işaretleyeceği bir bulgu.
- **İlk adım:** App.jsx:648'i Fragment ile sar: {p==='reject' && <><RejectCard data={d.reject} onRetry={onRetry}/><DisclaimerBar items={d.disclaimers}/></>}; smalltalk ve clarify path'lerini de aynı dosyada kontrol et.

### #2 — Production filtre field'larında (doc_type/kanun_kodu/madde_no) payload index YOK → her filtreli retrieval brute-force
- **Önem/Efor/Durum:** HIGH / S / HEMEN
- **Alt sistem:** retrieval-rag
- **Neden önemli:** Kodda teyit: hybrid_search.py:444/486/503 ve hyde.py:124 bu field'larda MatchValue filtreliyor AMA ensure_collection sadece domain+source index'liyor, rebuild_mursit_hybrid.py hiç index kurmuyor. 159K chunk'ta filtreli prefetch O(N) tarama yapıyor — 'lokal/hızlı' tez direğinin somut darboğazı, demo P95'ini ve eşzamanlı kapasiteyi belirler. Index ile 10-50x hızlanma.
- **Engel:** index kodu kutuda yazılır; canlı koleksiyona uygulamak Qdrant gerektirir
- **İlk adım:** ensure_collection'a doc_type(KEYWORD)+kanun_kodu(KEYWORD)+madde_no(INTEGER) create_payload_index ekle; aynısını rebuild_mursit_hybrid.py + tüm seed scriptlerine koy. Mevcut koleksiyon için tek-seferlik create_payload_index migration script'i yaz (Qdrant erişimi olunca koşulur).

### #3 — Halüsinasyon scorecard'ı construct-circular: gold-set onu ölçen detektörlerle kurgulanmış (P=1.0/R=1.0 tautolojik)
- **Önem/Efor/Durum:** HIGH / L / HEMEN
- **Alt sistem:** tests + bilimsel değerlendirme titizliği
- **Neden önemli:** 'SIFIR HALÜSİNASYON' projenin başlık-iddiası. RAG/NLP uzmanı bir hakem circular-benchmark'ı anında görür ve tüm kalkan kanıtını çürütür. Bu, en savunmasız akademik nokta — held-out + insan-gold iddiayı bilimsel olarak ayağa kaldırır.
- **Engel:** gerçek-Qwen halüsinasyon çıktıları lazım (eval/runs'a kayıtlıysa kutuda etiketlenebilir; yeni üretim GPU gerektirir)
- **İlk adım:** eval/runs'taki mevcut gerçek-LLM çıktılarından halüsinasyon-içerenleri 2 etiketçiyle İNSAN etiketle (Cohen κ raporla), detektörü o held-out sette ölç; mevcut P=1.0'ı 'detektör self-consistency' diye yeniden adlandır, gerçek recall'ı ayrı raporla.

### #4 — MCP retry_after sınırsız asyncio.sleep DoS açığı
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** backend güvenlik (retrieval/yargi_client.py)
- **Neden önemli:** Kodda teyit: yargi_client.py:312 'await sleep(retry_after_s + 1)' — dış servis verisi doğrudan sleep'e besleniyor, üst sınır yok. Güvenlik denetçisinin/jürinin ilk bakacağı SSRF-adjacent kontrol noktası. Tek satır fix.
- **İlk adım:** yargi_client.py:306'da MAX_RETRY_AFTER_S=60 sabiti tanımla, retry_after_s = min(float(...), MAX_RETRY_AFTER_S) uygula; orta vadede elle-sleep'i tenacity katmanına taşı.

### #5 — README/paper/tez arası LLM model çelişkisi: Qwen3.5-9B vs Qwen 2.5 14B
- **Önem/Efor/Durum:** HIGH / M / HEMEN
- **Alt sistem:** docs-thesis-competition
- **Neden önemli:** Reproducibility iddiasının (açık-kaynak → jüri bağımsız doğrular) en kırılgan noktası. Hakem README ile 9B çalıştırıp 14B sayılarını üretemeyince 'sayılar gerçek mi' güveni çöker. Akademik makalede 'ölçüm modeli ≠ sunulan model' düzeltilmeden gönderilemez. 'Qwen3.5' HF model adı muhtemelen hatalı.
- **İlk adım:** Tek 'üretim modeli' kararı ver; gerçek HF adını doğrula ('3.5' yanlışsa düzelt); TÜM dokümanlarda aynı string kullan; manşet sayıların hangi modelle alındığını dipnotla (ör. 'ablation 14B, üretim 9B re-run kuyrukta').

### #6 — Akademik makale taslağı (paper-draft.md) hâlâ placeholder-iskelet — kanıt var, entegre değil
- **Önem/Efor/Durum:** MEDIUM / L / HEMEN
- **Alt sistem:** docs-thesis-competition
- **Neden önemli:** SIU/TIDE-TR makalesinin omurgası. Kanıt (measured-results.md, ablation_study.md, scorecard.md) mevcut ama paper'da görünmüyor; hakem placeholder görürse reddeder. Emek değil, mevcut ölçümleri taşıma — en yüksek ROI'li tez-hazırlık adımı.
- **İlk adım:** measured-results+ablation+scorecard'taki gerçek değerleri paper §4'e mekanik taşı: tüm X.XX'leri doldur, '7 ajan'→'8 ajan+V2 policy', fuzzy 0.55→0.45, corpus→159k, benchmark→186 vaka sabitle; baseline karşılaştırması (genel-LLM vs ADALET halüsinasyon oranı) ekle.

### #7 — Sesli mod (STT/TTS) backend hazır ama frontend hiç bağlamamış — Erişilebilir Hukuk tezinin demo-yüzü yok
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** frontend-ux + multimodal
- **Neden önemli:** Üye-2 'Sesli Arayüz' tezinin ve Teknofest 'İnsanlık Yararına Teknoloji' kategorisinin somut kanıtı. Backend ödendi (lokal Whisper/Coqui); sadece köprü eksik — en yüksek ROI'li boşluk. Görme/okuma engelli vatandaş erişimi, jüri demosunda 'konuş-dinle' tam döngü.
- **Engel:** uçtan-uca test için lokal STT/TTS modelleri (GPU) gerekir; UI köprü kodu kutuda yazılır
- **İlk adım:** İki ince katman: (a) CGInput'a mikrofon → MediaRecorder → /multimodal/stt → input'a transkript; (b) MsgActions'a 'Sesli oku' → /multimodal/tts → <audio>. UI tarafı GPU'suz yazılır, e2e doğrulama kullanıcı GPU'sunda.

### #8 — React ErrorBoundary yok — tek bileşen hatası tüm ağacı çöküyor
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** frontend (React/Vite — src/)
- **Neden önemli:** Kodda teyit: src/ altında hiç ErrorBoundary yok. Üretim-kalite React'te temel kalite açığı; Teknofest canlı demosunda tek edge-case hata demonstrasyonu mahveder.
- **İlk adım:** Root.jsx'e üst-düzey ErrorBoundary ekle; chat ve panel bölgelerini ayrı boundary'lerle sar; catch'te Türkçe hata + 'Yeniden dene' butonu sun (react-error-boundary).

### #9 — Kalibrasyon val-set model seçimiyle çakışıyor (double-dip leakage)
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** predictive-ml
- **Neden önemli:** Calibration leakage gerçek ECE'yi olduğundan düşük gösterir; jüri/hakem fark ederse temperature-scaling tabanlı tüm confidence iddiası çöker. Confidence ekranı vatandaşa güven sinyali — yanlış kalibrasyon yanlış sinyal.
- **Engel:** yeni split ile re-eğitim/kalibrasyon GPU gerektirir; split-kodu kutuda yazılır
- **İlk adım:** stratified_split'e cal_frac=0.1 desteği (70/10/10/10 train/val/cal/test); calibrate_model.py'ye --split cal argümanı; checkpoint seçimini val'dan, temperature'ı ayrı cal split'inden al.

### #10 — Otomatik Qdrant/DB yedekleme cron'u kurulmuyor — runbook 'aktif' diyor ama init script kurmuyor
- **Önem/Efor/Durum:** HIGH / S / HEMEN
- **Alt sistem:** infra-devops
- **Neden önemli:** Hukuki üründe yedeği-olmayan veri = lansman blokeri. Jüri/danışman 'yedek aldınız mı, restore test ettiniz mi' diye sorar; script-var-kurulmuyor false-confidence yaratır.
- **Engel:** none (script yazılır; gerçek cron testi Hetzner gerektirir)
- **İlk adım:** hetzner-init.sh'ye adalet-backup.{service,timer} (günlük 03:00 → backup_qdrant --s3) ekle; restore-test'i runbook'ta zorunlu adıma çevir.

### #11 — Yarisma-ozeti.md doğrulanamayan/güncel-olmayan teknik iddialar içeriyor (default-OFF özellikler 'kanıt' diye sunulmuş)
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** docs-thesis-competition
- **Neden önemli:** Jüri açık-kaynak repoyu inceleyince (özetin kendi vaadi) opt-in/ölçülmemiş özelliğin kanıt diye sunulduğunu görürse tüm özet güveni düşer. Dürüst kapsam-sınırı projenin EN güçlü farkı — özetin kendisi ihlal etmemeli.
- **İlk adım:** Her teknik iddiaya 'durum' işareti koy (RAPTOR/graph-RAG → 'mimaride mevcut, opt-in, ölçülmedi'); test sayısını README 1313'e hizala; KVKK manşetini CLAUDE.md v2.2'ye uyumla; Imagine Cup 'Azure' iddiasını bulut-yok kırmızı-çizgisiyle netleştir.

### #12 — NLI cache namespace nli.py'nin set etmediği env var kullanıyor — model güncellemelerinde stale cache
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** Verify / Hallucination Core
- **Neden önemli:** Cache'lenmiş yanlış NLI verdict doğrudan ayırt edilemez. İki model versiyonu kıyaslayan benchmark'ta stale cache birini olduğundan iyi gösterir — değerlendirme reproducibility'sini geçersizler.
- **İlk adım:** nli.py modül-init'te os.environ['NLI_MODEL']=MDE_MODEL_ID set et VEYA cache.py _model_tag()'i MDE_MODEL_ID'i doğrudan import edecek şekilde değiştir; cache key'e model fingerprint (ad+mtime) ekle.

### #13 — finalize.py _compute_confidence NLI sinyali içermiyor — doğrulanmamış cevapta confidence 0.8+ olabilir
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** Verify / Hallucination Core
- **Neden önemli:** Confidence ekranı vatandaşa güven sinyali ve calibration test setinin temeli. NLI olmadan retrieval-skoru yüksek ama grounding'i zayıf cevap yüksek güven gösterir — yanlış sinyal, calibration iddiasını zayıflatır.
- **İlk adım:** verify_node'da nli_ratio'yu state'e kaydet; formülü 0.30*dom_conf+0.30*claim_ratio+0.20*retrieval+0.20*nli_ratio yap VEYA verify_reason 'neutral'/'low_score' içerdiğinde confidence'ı max 0.65'e clamp et.

### #14 — max_length=384 (calibrate) vs 512 (train/inference) — tokenizer dağılım kayması
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** predictive-ml
- **Neden önemli:** Temperature yanlış hesaplanırsa ECE≤0.05 kağıt üzerinde karşılanmış görünür ama production confidence'ları yanlış kalibre olur. Tek-değer fix, ölçüm bütünlüğü.
- **İlk adım:** calibrate_model.py'de --max-length default'unu 512 yap, metrics.json'dan otomatik oku; script başına assert args.max_length==trained_max_length hard-fail guard ekle.

### #15 — answer_risk.py str.casefold() kullanıyor — Türkçe İ/I claim-detection bug
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** Verify / Hallucination Core
- **Neden önemli:** Türkçe büyük-İ/küçük-ı casefold yanlış normalize eder → bazı riskli iddia kalıpları (İ ile başlayan) detektörden kaçar. Sıfır-halüsinasyon kırmızı-çizgisinin kenar-vakası, projede zaten çözülmüş tr_lower pattern'i var.
- **İlk adım:** answer_risk.py'deki .casefold()/.lower()'ı tr_lower (retrieval.turkish_text) ile değiştir; dosyadaki diğer normalize çağrılarını da tara.

### #16 — Qwen2-VL fallback OCR bozuk: apply_chat_template + process_vision_info kullanılmıyor → üretilen metin boş
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** backend/multimodal
- **Neden önemli:** Tesseract n_chars<50 olduğunda Qwen2-VL fallback tek alternatif; kırıksa karmaşık belge (tapu/mahkeme kararı) fotoğrafı boş metin döndürür, ajan girişi sıfırlanır. Misafir-haklarına önyük.
- **Engel:** gerçek doğrulama Qwen2-VL modeli (GPU) gerektirir; kod düzeltmesi kutuda yapılır
- **İlk adım:** ocr.py:252'yi HF örneğine uygunla: messages→apply_chat_template→process_vision_info→processor(text,images). Mevcut çağrı imzasını HF Qwen2-VL kartıyla hizala.

### #17 — STT no_speech_prob filtresi yok — Whisper sessiz/gürültülü segmentte halüsinasyon üretiyor
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** backend/multimodal
- **Neden önemli:** Sesli soru girdisinde halüsinasyon metin doğrudan LangGraph state'ine girip yanlış hukuki değerlendirmeye yol açar — sıfır-halüsinasyon kırmızı-çizgisi ihlali. Sesli mod köprüsü (rank 7) açılınca üretim-kritik.
- **İlk adım:** stt.py döngüsünü 'if segment.no_speech_prob < 0.6: append' ile filtrele; ortalama no_speech_prob'u STTUploadResponse.confidence'a ekle.

### #18 — Qwen-VL model yüklemesinde asyncio.Lock yok — eş zamanlı ilk istek model'i iki kez GPU'ya yükler
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** backend/multimodal
- **Neden önemli:** Çoklu eş-zamanlı OCR (yük testi/demo) altında GPU OOM veya yarım-model. llm.py'de zaten çözülmüş lock pattern'i var, tutarlılık için OCR'a da uygulanmalı.
- **İlk adım:** ocr.py'ye modül-level _qwen_vl_lock=asyncio.Lock() ekle, _load_qwen_vl()'i lock altında çalıştır, yüklü modeli modül-değişkende sakla, lru_cache'i kaldır (llm.py kalıbı).

### #19 — CI docker-build smoke yalnız build ediyor — container'ı boot etmiyor (healthcheck yok)
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** infra-devops
- **Neden önemli:** Build-yeşil ama boot-kırmızı image ilk deploy'da patlar. World-class CI 'artifact gerçekten çalışıyor mu' doğrular; salt build dünya-standardının altında.
- **İlk adım:** docker-build job'una: docker run -d -e LLM_MODE=mock -e PRELOAD_MODELS=0 + /health 200 bekleme döngüsü + docker logs hata-grep + exit-code kontrolü ekle.

### #20 — OCR güven skoru pipeline boyunca iletilmiyor — ajanlar düşük-kaliteli OCR üzerine kesin hukuki sonuç üretiyor
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** backend/multimodal
- **Neden önemli:** World-class RAG (Ragas) kaynak güvenilirliğini propagate eder; ADALET fotoğraf kalitesinden bağımsız aynı kesinlikte sonuç veriyor. Tez+yarışma değerlendirmesinde gözden kaçmaz.
- **İlk adım:** image_to_data() conf>0 ortalamasını OCRUploadResponse.ocr_confidence'a ekle; ImageAttachmentInput.ocr_confidence ile state'e taşı; <0.6 attachment'ta verify ek-uyarı.

### #21 — Frontend prod deploy topolojisi tutarsız (relative fetch + Vercel rewrite yok + CSP backend'i dışlıyor + Caddy frontend serve etmiyor)
- **Önem/Efor/Durum:** HIGH / M / HEMEN
- **Alt sistem:** infra-devops
- **Neden önemli:** Teknofest/jüri canlı URL ister. Bütünleşik prod yolu yoksa demo yalnız localhost'ta yaşar — doğrudan yarışma riski.
- **Engel:** none (karar+config; canlı doğrulama deploy gerektirir)
- **İlk adım:** Topoloji seç: (A) Vercel→vercel.json rewrites + CSP connect-src backend + CORS; VEYA (B) Caddy file_server+SPA fallback (aynı-origin). Seçimi deploy-staging.md'ye yaz.

### #22 — Per-token setTurns — streaming'de her token için React re-render
- **Önem/Efor/Durum:** LOW / M / HEMEN
- **Alt sistem:** frontend (React/Vite — src/)
- **Neden önemli:** LLM streaming UX'in en görünür kısmı; düşük-end cihazda jank, DevTools Profiler'da ilk fark edilen. Demo izlenimini düşürür.
- **İlk adım:** Token'ları useRef (draftBufRef) ile biriktir, requestAnimationFrame/50ms debounce ile tek setTurns'e sıkıştır; veya draftText'i ayrı useState'te tutup sadece ilgili TurnView'e bağla.

### #23 — CI eval-gate yalnız deterministik scorecard koşuyor — policy_eval/edge_cases/verify_calibration regresyon koruması dışında
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** tests + eval-rigor
- **Neden önemli:** Kapsam-dışı (ceza/aile) kırmızı-çizgisi ve injection-karar-sağlığı her commit'te korunmuyor. Hepsi MockLLM/GPU'suz koşar, düşük efor yüksek koruma.
- **İlk adım:** CI eval-gate'e policy_eval deterministik alt-kümesi (oos reject + injection eşik-assert) + verify_calibration model-free P/R baseline snapshot-compare ekle.

### #24 — Geri bildirim oyu hiçbir yere gitmiyor — backend feedback route var ama bağlanmamış
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** frontend-ux
- **Neden önemli:** Langfuse/eval döngüsüne minimal sinyal bile RLHF-vari iyileştirme ve 'canlı kalite ölçümü' anlatısı sağlar. Sahte 'teşekkürler' yerine gerçek kayıt.
- **İlk adım:** api.js'e sendFeedback({conversation_id,turn,vote,anonymous:true}) → POST /api/feedback ekle; MsgActions vote handler'ını bağla.

### #25 — Brier Score hesaplanmıyor — README hedefi ölçümsüz
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** predictive-ml
- **Neden önemli:** README'de hedef olarak duran Brier Score hiç raporlanmıyor; calibration anlatısının eksik metriği. Tek-fonksiyon ekleme.
- **Engel:** eval-set üzerinde koşmak eğitilmiş model+veri gerektirir; kod kutuda yazılır
- **İlk adım:** eval_predict.py evaluate()'e brier=mean(sum((probs-one_hot)**2)) ekle, print_scorecard'da README hedefiyle kıyasla.

### #26 — Verify retrieval-bound: evidence ≤500-char snippet, tam-madde grounding yok (+ citation.verify_claim ölü kod)
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** retrieval-rag
- **Neden önemli:** Doğru-madde-yanlış-snippet false-drop'unu kapatır ve CLAUDE.md §1 sözleşmesini gerçekten karşılar. citation.verify_claim MevzuatClient.fetch_madde olmadığından AttributeError ile kırık — 'canlı doğrulama var' yanılsaması veriyor.
- **Engel:** tam-madde fetch ölçümü Qdrant/MCP gerektirir
- **İlk adım:** İki-taşla: MevzuatClient'a fetch_madde(kanun_kodu,madde_no) ekle (ölü verify_claim'i canlandırır) VEYA verify_claim+CitationClaim'i sil (KISS); evidence-genişletmeyi cited source_id'nin tam-madde'siyle besle.

### #27 — Tez 1/2/3 boş şablon + Tez 4 (predictive) yok ama ADR-009 ona link veriyor; docs '3 tez' der, proje 4
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** docs-thesis-competition
- **Neden önemli:** 4-tez anlatısı akademik meşruiyet; kırık çapraz-referans ve '3 vs 4' tutarsızlığı organizasyon zaafı sinyali. Tez-3'teki YANLIŞ teknik sayılar (Levenshtein/0.85/500) ölçülmüş gerçekle çelişiyor.
- **İlk adım:** Tez-3 yanlışlarını düzelt (rapidfuzz/0.45/186); ADR-009'un kırık tez-4 referansını çöz (tez-4-predictive.md oluştur — 'silver yanılsaması' anlatısı hazır VEYA referansı kaldır); docs/README 'theses/' satırını 4-tez'e güncelle.

### #28 — Dokümanlar arası tutarsız gold-set/vaka sayıları (verify_gold 31/59/24.5k; benchmark 186 vs 200/500) + eski eşik/topoloji (fuzzy 0.55, '7-Agent')
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** docs-thesis-competition
- **Neden önemli:** Tek-doğru-kaynak ihlali; açık-kaynak jüri tutarsızlık görür. Sayıları tek script'ten (scorecard.py) çekmek reproducibility'yi sağlamlaştırır.
- **İlk adım:** scorecard.py breadth tablosunu single-source-of-truth yap; PROJE-DURUMU 31→59, measured-results 24.5k→59, paper/tez 200/500→186; ADR-001/architecture'ı fuzzy 0.45 + '8-Agent+V2' yap.

### #29 — Benchmark gold-answer içermiyor → faithfulness/context-recall (ragas) hiç koşulmamış
- **Önem/Efor/Durum:** MEDIUM / L / HEMEN
- **Alt sistem:** tests + eval-rigor
- **Neden önemli:** RAG paper'larının standart metriği faithfulness/context-recall; retrieval@k 'cevap doğru mu'yu yanıtlamaz. 40-gold alt-küme sistemi SOTA RAG değerlendirme normuna hizalar.
- **Engel:** ragas gerçek-Qwen koşumu GPU gerektirir; gold-answer etiketleme kutuda yapılır
- **İlk adım:** benchmark_v2 alt-kümesine (her domain ~5, ~40 toplam) insan-yazılı gold_answer ekle (kutuda); ragas_full.py'yi bu sette koş (GPU oturumunda).

### #30 — Edge-case/verify-ablation/prompt-injection harness'ları gerçek-LLM ile hiç koşulmamış — verify'ın RED gücü ölçülmemiş
- **Önem/Efor/Durum:** MEDIUM / M / BLOKE
- **Alt sistem:** tests + eval-rigor
- **Neden önemli:** Verify'ın cevabı REDDETME gücü 'uydurmaz' iddiasının asıl kanıtı; jüri 'kötü-niyetli girdide ne yapıyor' sayısal cevabını ister. Paper §4.3'ün boş satırlarını doldurur.
- **Engel:** GPU (LLM_MODE=llamacpp) gerektirir — runtime-bloke
- **İlk adım:** GPU oturumunda 3 harness koş, eval/runs'a kaydet: edge_cases (24 OWASP RED-rate), verify_ablation --include-edge (adversarial block-rate), prompt_injection must_not_contain çıktı-kontrolü.

### #31 — İstatistiksel güç zayıf: kategori-altı N küçük + insan inter-annotator (Kappa) RAG/verify gold'da yok
- **Önem/Efor/Durum:** MEDIUM / L / HEMEN
- **Alt sistem:** tests + eval-rigor
- **Neden önemli:** Tek-haneli N domainler ve κ'sız gold istatistik güvenilirliği zayıflatır; Wilson CI zaten var ama her tabloda kullanılmıyor.
- **Engel:** none (etiketleme kutuda; ikinci etiketçi insan-kaynağı gerekir)
- **İlk adım:** verify_gold'u kategori başına ≥25-30'a büyüt (özellikle contradiction); idari/tapu tek-haneli domainlere benchmark vakası ekle; tüm oran-metriklerini stats.py Wilson CI ile sun.

### #32 — Chunking semantic-aware değil: sabit 1200-char window, mevzuat contextual-prefix yok
- **Önem/Efor/Durum:** MEDIUM / M / BLOKE
- **Alt sistem:** retrieval-rag
- **Neden önemli:** Mevzuat fıkra/bent-aware sub-chunking + kanun_adi+madde_baslik prefix (Anthropic contextual-retrieval'ın LLM'siz deterministik versiyonu) retrieval@k'yı ölçülebilir artırır. Karar metni zaten section-aware — odak mevzuat.
- **Engel:** re-seed + ölçüm Qdrant/GPU gerektirir
- **İlk adım:** Mevzuat sub-chunk'a 'Türk Borçlar Kanunu Madde 299 (Kira sözleşmesi tanımı): ...' prefix göm; re-seed + eval_run ile retrieval@k ölç (önceki ham-split net-negatif'ten FARKLI yaklaşım).

### #33 — Step-back rewrite konuşma-dili sorgularda production-default kapalı — reranker'a colloquial girip tier-sort heuristic'iyle maskeleniyor
- **Önem/Efor/Durum:** MEDIUM / M / BLOKE
- **Alt sistem:** retrieval-rag
- **Neden önemli:** Cross-encoder konuşma-dili TR'de güvenilmez (ölçülmüş); step-back resmî-jargon sorgusuyla reranker'a girince kök-neden düzeltmesi olur, tier-sort maskesi yerine. Mevcut-ama-kapalı SOTA aracını default-on yapıp ölçmek.
- **Engel:** GPU+Qdrant ile ölçüm gerektirir
- **İlk adım:** Step-back'i konuşma-dili sorgularda default AÇ (speculative latency bütçesinde), eval_run ile madde_recall@5 + P95 ölç.

### #34 — Reproducibility paketi parçalı: paper Ek-A komutları gerçek script'lerle eşleşmiyor, freeze_baseline + tek-komut jüri-demo runbook yok
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** docs-thesis-competition
- **Neden önemli:** Açık-kaynak reproducibility iddiasının somutu; jüri demo runbook'u (sabit sorular + beklenen policy-yolu) demonun deterministik kısmını garantiler.
- **Engel:** freeze_baseline gerçek-LLM koşumu GPU gerektirir; runbook+Ek-A düzeltmesi kutuda
- **İlk adım:** paper Ek-A seed komutlarını gerçek script'lere düzelt; jüri-demo runbook'u yaz (5 sabit soru: kıdem/depozito/ayıplı-mal/kapsam-dışı-ceza/eksik-bilgi → beklenen policy-yolu + örnek çıktı); LLM_MODE=mock deterministik kısmı ayır.

### #35 — Supabase token'larında issuer (iss) doğrulaması devre dışı
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** backend güvenlik
- **Neden önemli:** iss doğrulamasız JWT, başka Supabase projesinden token kabul riski. Tek-satır güvenlik sertleştirmesi.
- **İlk adım:** SUPABASE_ISSUER'ı env'den al, options={'verify_iss':True} ile birleştir; .env.example'a satır ekle.

### #36 — LLM-as-Judge tek-model self-evaluation (Qwen kendini yargılıyor) — bias/insan-korelasyon kontrolü yok
- **Önem/Efor/Durum:** MEDIUM / M / BLOKE
- **Alt sistem:** tests + eval-rigor
- **Neden önemli:** Tek-model judge bias'ı ölçülmemiş; küçük insan-korelasyon (Spearman ρ) judge validity sağlar, paper'a 'judge validity' alt-bölümü ekler.
- **Engel:** gerçek-LLM judge + ikinci model GPU gerektirir
- **İlk adım:** 20-cevap alt-kümede insan faithfulness/tone puanı topla, LLMJudge ile Spearman ρ raporla; mümkünse farklı lokal model ile çapraz-judge.

### #37 — Citation popover dokunmatik cihazlarda açılamıyor + AgentTrace toggle aria-controls eksik + yazı-boyutu zoom kullanıyor (WCAG)
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** frontend-ux a11y
- **Neden önemli:** WCAG 1.4.13/4.1.2/1.4.4 ihlalleri; 'İnsanlık Yararına Teknoloji' ve erişilebilirlik anlatısı için demo-kritik. Hepsi S-M efor, kümülatif a11y kazancı.
- **İlk adım:** cite-pop mobil tap'ı ikiye ayır (ilk tap=aç, ikinci=jump); AgentTrace toggle'a aria-controls + body'ye id; yazı-boyutunu zoom yerine --text-scale rem-tabanlı yap.

### #38 — Container image güvenlik taraması (Trivy/Grype) yok + base image'lar digest-pinli değil
- **Önem/Efor/Durum:** MEDIUM / M / HEMEN
- **Alt sistem:** infra-devops
- **Neden önemli:** Supply-chain reproducibility açığı; llama.cpp:server-cuda mutable tag en riskli. Açık-kaynak güvenlik anlatısını güçlendirir.
- **İlk adım:** docker-build sonrası trivy-action ekle (HIGH/CRITICAL fail/rapor); production base image'ları @sha256 digest'le pinle (özellikle llama.cpp:server-cuda).

### #39 — TTS hukuki kısaltma normalize etmiyor (TL/Md./TTK harf-harf okunuyor) + Tesseract PSM sabit 6
- **Önem/Efor/Durum:** MEDIUM / S / HEMEN
- **Alt sistem:** backend/multimodal
- **Neden önemli:** Sesli mod köprüsü (rank 7) açılınca TTS kalitesi demo-kritik; PSM 6 dikey-sütun/form belgelerinde yanlış okur. İkisi de multimodal sunum kalitesi.
- **İlk adım:** _LEGAL_ABBREVS sözlüğü ({'Md.':'Madde','TL':'Türk lirası','TTK':'Türk Ticaret Kanunu'}) ile _prepare_text re.sub expand; ocr.py'ye _best_psm_ocr (PSM 3 dene→threshold altında PSM 6).

### #40 — agents-graph kod-kalite kümesi: LLM-hatası retry bütçesi tüketiyor + _tr_lower 4 modülde çoğalmış + chat confidence=1.0 + RARR_ENABLED modül-yükte sabit + ölü/gereksiz import'lar
- **Önem/Efor/Durum:** LOW / S / HEMEN
- **Alt sistem:** agents-graph
- **Neden önemli:** Tek-tek LOW ama kümülatif kod-kalite/maintainability borcu; LLM-OOM hatası kullanıcıya yanlış 'red-line reddi' olarak gidiyor (güven kalibrasyonunu bozar), tr_lower çoğaltması sessiz tutarsızlık riski. Hepsi S, GPU'suz.
- **İlk adım:** backend/agents/utils/turkish.py tek tr_lower; LLM crash'i ayrı llm_error_count ile say (retry bütçesini yeme, infrastructure_error mesajı); RARR_ENABLED'ı _rarr_enabled() fonksiyonuna çevir; chat path confidence=0.7/verified=False; gövde-içi import'ları modül başına taşı.

## SOTA Araştırma Boşlukları (GitHub + web)

### tr-legal-nlp
2024-2026 Türkçe hukuk NLP/RAG SOTA'sı, ADALET'in zaten benimsediği Mursit embedder'ının arkasındaki ekosistemin (NewMind AI / nmmursit) hızla olgunlaşmasıyla şekillendi. Üç ayağı var: (1) RETRIEVAL — Mursit ailesi artık Base'in ötesine geçti: Mursit-Large-TR-Retrieval (0.4B, 56.43 MTEB) ve Qwen3 tabanlı Mursit-Embed-Qwen3-1.7B/4B-TR embedder'ları; ayrıca EMNLP 2025 Findings'te TR-MTEB (6 görev, 26 dataset, 34.2M cümle çifti ile eğitilmiş iki TR-özel model) ve TurkEmbed4Retrieval (arXiv 2511.07595) Türkçe retrieval için standartlaştı. En çarpıcı gelişme TurkColBERT (arXiv 2511.16528, aynı NewMind/Mursit grubu): Türkçe için late-interaction (ColBERT) checkpoint ailesi — ColmmBERT-base-TR domain görevlerinde dense'e karşı +13.8% mAP, late-interaction modelleri 3-5x daha küçükken dense'i geçiyor, 1M-param colbert-hash-nano-tr 600B-param e5-large'ın mAP'ının %71'ini koruyor; PLAID yerine 0.5253 NDCG@100 ve latency 73.6ms→35.2ms. (2) GENERATION/REASONING — Mecellem (arXiv 2601.16018) hukuk için sıfırdan + sürekli ön-eğitilmiş Qwen3 1.7B/4B-TR modelleri; HukukBERT (arXiv 2604.04790) 18GB temizlenmiş hukuk korpusu, Legal Cloze Top-1 %84.40, mahkeme kararı yapısal segmentasyonda %92.8 doküman geçiş oranı. (3) EVAL/GROUNDEDNESS — burada SOTA en çok ilerledi: RAGTruth-TR (17.8K, span-düzeyli halüsinasyon etiketleri: Evident Conflict / Baseless / Subtle), Muhakim (8B reward model, beş hukuki boyutta MoE-gated: madde-atıf doğruluğu, hukuki doğruluk, içtihat-atıf, dilsel kalite, derinlik), reasoning-odaklı legal retrieval benchmark'ları (RegLab/Stanford: query-passage düşük leksik örtüşme → reasoning-rollout query expansion ile Recall@10 +10pp). Açık TR hukuk IR dataset'leri de boş zemin değil artık: newmindai/regulation-retrieval (264K, BEIR-format özelge), caselaw-retrieval (4.15K), contract-retrieval, EuroHPC-Legal (116 uzman QA), ms-marco-turkish-triplets (920K). Altyapı tarafında yargi-mcp standart erişim katmanı. ADALET mimari olarak (8-ajan, fail-closed verify, 4-katman grounding, ColBERT rerank) bu SOTA'nın ÖNÜNDE ya da hizasında; geride kaldığı yer model-seçimi (daha yeni TR-native checkpoint'ler) ve standart açık eval/dataset'lere bağlanma.

- **[HIGH/moderate]** Türkçe-native late-interaction (ColBERT) checkpoint'i ile stored-ColBERT rerank — *eksik:* ADALET stored-ColBERT rerank'ı GENEL bge-m3 ColBERT vektörleri üzerinden yapıyor (Türkçe-native değil). TR-native ColmmBERT/ColumBERT-small-TR'ye geçiş aynı pipeline'da madde/emsal rerank kalitesini ölçülebilir şekilde artırabilir; ADALET zaten Mursit-Base'i benimsediği için aynı grubun ColBERT'ine geçmek doğal devam. — *kaynak:* https://arxiv.org/pdf/2511.16528
- **[HIGH/easy]** RAGTruth-TR ile verify/grounding kalibrasyonu (span-düzeyli halüsinasyon gold) — *eksik:* ADALET'in verify gold setleri kendi-üretimi ve küçük (hallucination gold 104, verify_gold 31, NLI-TR 28). RAGTruth-TR, 4-katman verify'ı (özellikle L3 NLI eşiklerini ve risk_guard veto'larını) BAĞIMSIZ, dış, span-etiketli bir set üzerinde kalibre etmeyi sağlar — eşik over-fit riskini düşürür, paper/jüri için 'dış benchmark' iddiası verir. Subtle Baseless sınıfı ADALET'in süre-uygunluk halüsinasyonu (memory'deki bilinen zayıflık) gibi ince çıkarım hatalarını yakalamada doğrudan ilgili. — *kaynak:* https://huggingface.co/datasets/newmindai/RAGTruth-TR
- **[MEDIUM/moderate]** Çok-boyutlu hukuki cevap-kalitesi ödül modeli (Muhakim) ile LLM-as-judge eval — *eksik:* ADALET'in eval'i scorecard PASS/FAIL gate + Wilson CI + grounding-odaklı; çıktının HUKUKİ KALİTESİNİ (derinlik, içtihat-atıf isabeti, dilsel kalite) çok-boyutlu skorlayan bir hakem yok. Muhakim lokal çalışan (8B, kırmızı-çizgi uyumlu) bir eval node'u/CI metriği olarak eklenebilir — rakip-LLM kıyası BLOKE olduğu için (.env API key yok) Muhakim 'lokal hakem' bu boşluğu doldurur. Yalnız eval'de, üretim yolunu değiştirmez. — *kaynak:* https://huggingface.co/newmindai/Muhakim
- **[HIGH/easy]** Açık, standart TR hukuk retrieval benchmark'larına (BEIR-format) bağlanma — *eksik:* ADALET'in retrieval/madde-recall ölçümleri kendi 159K corpus'u + kendi 8-domain benchmark'ı üzerinde — DIŞ, standart, hakemli bir karşılaştırma noktası yok. regulation-retrieval (vergi domain ADALET'in 8 alanından biri) ve caselaw-retrieval (emsal corpus zayıflığını — memory: emsal corpus %75 anayasa, Yargıtay tüketici eksik — doğrudan kapatabilir) BEIR-format olduğu için ADALET'in eval harness'ına nDCG@10/Recall@k olarak takılabilir ve hem eval hem corpus-zenginleştirme sağlar. Paper için 'standart benchmark'ta X skor' iddiası. — *kaynak:* https://huggingface.co/datasets/newmindai/regulation-retrieval
- **[MEDIUM/moderate]** Reasoning-rollout query expansion (yapılandırılmış hukuki muhakeme ile retrieval öncesi) — *eksik:* ADALET adaptive HyDE/MQ routing'e sahip ama bunlar tek-adım genişletme; çok-adımlı 'hukuki muhakeme rollout'u → alt-sorulara/maddelere ayrıştır → her birini retrieve' deseni yok. Mevcut adaptive routing knob'larına opt-in bir 'reasoning-rollout' modu olarak eklenebilir (düşük leksik-örtüşmeli madde aramalarında — ADALET'in bilinen darboğazı madde@5). Kullanıcı GPU ile A/B ölçmeli (kör eklenmemeli). — *kaynak:* https://reglab.github.io/legal-rag-benchmarks/
- **[MEDIUM/hard]** Daha güçlü TR-native embedder (Mursit-Large / Mursit-Embed-Qwen3) seçeneği — *eksik:* ADALET Mursit-Base-TR (768-dim) kullanıyor (kanun@5 +7pp ölçülmüş). Mursit-Large veya Qwen3-embed'e geçiş daha yüksek recall verebilir ama embedding-swap re-index + latency maliyeti gerektirir; ADALET memory'sinde 'embedding swap' KULLANICI-RUNTIME-GEREKTİREN olarak işaretli. Bu yüzden öneri: kör değiştirme değil, kullanıcı GPU/Qdrant ile Mursit-Large'ı kendi 8-domain benchmark'ında A/B ölç; Base'in P95 -42% avantajını kaybetmeye değer mi karar ver. — *kaynak:* https://huggingface.co/newmindai

### hallucination-verify (halüsinasyon-tespiti / citation-grounding / faithfulness)
2024-2026 dünya-standardı, ADALET'in 4-katman + risk_guard hattının ötesinde dört yönde ilerledi: (1) Encoder tabanlı token/span-level grounding artık fine-tuned özel modeller (LettuceDetect/ModernBERT, RAGTruth üzerinde F1≈79; Türkçe için Turk-LettuceDetect newmindai modelleri F1≈0.73) — ADALET'in eski rapidfuzz token-coverage fallback'inden ölçülebilir derecede güçlü. (2) Faithfulness için ucuz-ama-GPT4-seviye fact-checker'lar: MiniCheck-FT5 (770M, EMNLP'24) ve AlignScore/TrueTeacher — LLM-as-judge maliyeti olmadan claim-evidence entailment. (3) Citation-grounding hukuka özgüleşti: 'Citation Grounding via Legal Citation Graphs' (2606.00898) atıfları corpus'tan türetilen bir atıf-grafiğine karşı doğruluyor + CG-DPO ile algoritmik tercih-çifti üretiyor; Stanford 'Hallucinating Law' (Dahl 2024) ve 'Hallucination-Free?' (2024) hukuki RAG'ın bile %17-33 halüsinasyon yaptığını ölçtü → atıf-varlık-doğrulaması ve calibrated-refuse (Trust-Align, 2409.11242) zorunlu kabul ediliyor. (4) Model-içi sinyaller: semantic entropy (Nature 2024) ve ucuz Semantic Entropy Probes (SEP) ile üretim-öncesi belirsizlik; RAGognizer (2604.15945) ve ReDeEP (2410.11414) üretim-anında/mekanistik tespit. ADALET mimari olarak (fail-closed, NLI, risk-veto, eval-gate) zaten bu literatürün en iyi pratiklerinin çoğunu uyguluyor; en somut açık, fine-tuned Türkçe grounding modelinin fiilen devrede olmaması ve atıf-VARLIK (existence) doğrulamasının corpus-graph yerine sadece regex/retrieval'a dayanması.

- **[HIGH/moderate]** Fine-tuned Türkçe token-level grounding modelini fiilen devreye almak (Turk-LettuceDetect, context-aware) — *eksik:* ADALET'in Layer-2.5 'LettuceDetect'i fiilen ham/context-aware modeli ÇALIŞTIRMIYOR: backend/verifier/lettuce.py'de use_raw_model default False ve ham HF token-classification yolu context göremediği için (H3 bug) devre dışı; pratikte rapidfuzz token-coverage fallback'i koşuyor. Yani 'Lettuce katmanı' adı var, fine-tuned Türkçe grounding gücü yok. Bağlanırsa NLI'dan bağımsız, gerçek token-level kanıt-örtüşmesi elde edilir. — *kaynak:* https://arxiv.org/abs/2509.17671 + https://huggingface.co/blog/nmmursit/turkish-hallucination-detection-models
- **[HIGH/moderate]** Atıf-VARLIK doğrulaması için legal citation-graph (CG) + algoritmik DPO tercih-çifti üretimi — *eksik:* ADALET atıf doğruluğunu retrieval (madde getirildiyse 'var') + parse_citation regex + risk_guard'ın absürt-tavanlarıyla (madde>1100, daire>30) yapıyor — bunlar uydurma-imkânsız atıfları yakalar ama 'gerçek var olan ama yanlış-madde' (law-swap/article-swap) sınıfını ölçmüyor ve temporality (mülga/yürürlük tarihi) hiç kontrol edilmiyor. Mevcut 159K corpus'tan (Yargıtay+AYM+law) bir madde-VARLIK indeksi + CP/CR/CT ayrıştırması eklenebilir; ADALET zaten LLM'siz/deterministik tercih ettiği için CG-DPO'nun algoritmik tercih-çifti üretimi tahmin/triaj fine-tune'larına da uyar. — *kaynak:* https://arxiv.org/html/2606.00898
- **[MEDIUM/moderate]** Tek, hızlı, GPT-4-seviye faithfulness fact-checker (MiniCheck / AlignScore / TrueTeacher) ile NLI'ı güçlendirme — *eksik:* ADALET'in L3'ü XNLI mDeBERTa (yalnız entail/contradict, tek pick_evidence snippet'i) — çok-cümleli sentez gerektiren ('A maddesi B koşuluyla C sonucunu verir') desteği veya birden çok snippet'ten türeyen desteği zayıf yakalar. Bir Türkçe-uyarlı MiniCheck-benzeri checker (veya AlignScore-TR) NLI'a paralel ikinci-görüş katmanı olarak eklenip 'multi-evidence faithfulness' skoru üretebilir; deployable (770M, lokal, bulut yok → kırmızı çizgiye uygun). — *kaynak:* https://github.com/Liyan06/MiniCheck (arxiv 2404.10774)
- **[MEDIUM/moderate]** Atomic claim decomposition (FActScore/RefChecker tarzı) — cümle-claim yerine atomik önerme doğrulama — *eksik:* ADALET claim'leri taslak içinde [src:]-etiketli cümle/segment düzeyinde işliyor; tek cümlede birden çok önerme varsa (biri grounded biri uydurma) cümle bütününün fuzzy/NLI skoru desteksiz parçayı maskeleyebilir. Draft sonrası bir atomik-decompose adımı (deterministik bağlaç/noktalama bölme + her atom için ayrı verify) finalize'ın _filter_to_verified'ını parça düzeyine indirir → kapsam-koruyan ama daha keskin. Salt-Python decompose ile LLM'siz başlanabilir. — *kaynak:* https://github.com/amazon-science/RefChecker (arxiv 2405.14486)
- **[MEDIUM/moderate]** Kalibre edilmiş çekince/refuse skoru (Trust-Align / learning-to-refuse) ve güven-skoru kalibrasyonu — *eksik:* ADALET'in reddi fail-closed + risk-veto ile ikili (geç/reddet) ve UI'da bir güven-skoru gösteriyor — ama bu skorun kalibrasyonu (gösterilen %X ≈ gerçek doğruluk mu?) ölçülmüyor ve 'aşırı-tereddüt' (over-hedge) bir kalibrasyon hedefi değil. Trust-Score'un grounded-refusal + calibration ekseni, mevcut eval scorecard'ına 'reliability/abstention-quality' kolonu olarak eklenebilir; güven-skoru reliability-diagram (ECE) ile kalibre edilebilir. (Eğitim tarafı GPU gerektirir → kullanıcı-runtime.) — *kaynak:* https://arxiv.org/pdf/2409.11242
- **[LOW/hard]** Model-içi belirsizlik sinyali: semantic entropy / Semantic Entropy Probes (üretim-öncesi confabulation tespiti) — *eksik:* ADALET'in tüm verify'ı kaynak-temelli (post-hoc, dış kanıt) — modelin kendi belirsizliğini hiç okumuyor; LLM_MODE=llamacpp lokal Qwen hidden-state/logprob'larına erişim mümkün ama kullanılmıyor. Üretim-öncesi bir SE/SEP sinyali (veya basit token-logprob entropisi) düşük-güven cevapları daha erken triaj/clarifier'a yönlendirebilir. Lokal model gerektirdiği için kör eklenemez — kullanıcı GPU/llamacpp ile ölçmeli. — *kaynak:* https://www.nature.com/articles/s41586-024-07421-0 + https://arxiv.org/pdf/2406.15927
- **[LOW/easy]** Faithfulness regresyon ölçümü için RAGTruth-TR + LLM-AggreFact ile dış-benchmark hizalama — *eksik:* ADALET'in eval'i kendi gold setlerine (hallucination 104, verify_gold 31, NLI-TR 28) dayanıyor — güçlü ama dışarıyla kıyaslanamaz/küçük. RAGTruth-TR'yi ek bir eval-split olarak bağlamak, verify katmanının F1'ini literatür-karşılaştırılabilir kılar (tez/paper için doğrudan baseline tablosu) ve eşik kalibrasyonunu daha geniş dağılımda doğrular. Salt eval (üretimi etkilemez) → düşük risk. — *kaynak:* https://huggingface.co/datasets/newmindai/RAGTruth-TR + https://arxiv.org/abs/2404.10774

### multiagent-legal
2024-2026 dünya-standardı çoklu-ajan hukuk asistanı mimarisi 5 eksende olgunlaştı: (1) ROL-TABANLI HUKUK BÜROSU benzetimi — ChatLaw (6.8K★, MoE+KG+4-ajan SOP), LawLuo (resepsiyon/avukat/sekreter/PATRON-ödül-modeli+ToLC klarifikasyon ağacı), AgentsCourt/AgentCourt (savcı-savunma-hakim duruşma debate'i). ADALET'in 8-ajan+debate mimarisi BU PARADİGMADA, hatta çoğundan daha sert (fail-closed verify, 4-katman grounding). (2) DOĞRULAMA artık SOTA'nın merkezi: salt NLI/fuzzy yerine CITATION-GRAPH GROUNDING (gerçek mahkeme atıf ağına karşı doğrulama: madde-VAR-MI + bağlam-RELEVANS + TEMPORAL geçerlilik), claim-decomposition→retrieve→verify pipeline'ı (faithfulness≠correctness ayrımı netleşti), CiteGuard/RAGentA multi-agent atıf doğrulaması. (3) SEMBOLİK/FORMAL doğrulanabilir akıl yürütme: statü→ontoloji şeması→sembolik çıkarım (statutory hesap doğruluğu %18.8→%76.4), kara-kutu LLM'in denetlenemez çıkarımına alternatif. (4) ÖZ-EVRİLEN ajanlar: AgentCourt 1000 simüle-dava sonrası experience/case/law repository'leriyle ölçülen iyileşme; LawLuo boss-agent PPO ödül modeliyle çıktı kalibrasyonu — statik prompt yerine deneyimden öğrenme. (5) AGENTIC BENCHMARK devrimi: LegalBench/LexGLUE (kısa-ufuk QA) ARTIK YETERSİZ sayılıyor; yeni standart LegalAgentBench (37 araç, 17 korpus, ara-adım progress-rate), MASLegalBench (950 dedüktif soru, Meta-LLM+alt-ajan koordinasyon hata-modları), Harvey LAB (1250+ uzun-ufuk görev, 75K rubric, ALL-PASS kısmi-kredi-yok değerlendirme). ADALET çoğu mimari öğeyi (RAG+debate+verify+clarifier+tahmin) ZATEN kapsıyor; SOTA-altı kaldığı yer: citation-graph/temporal doğrulama, formal-symbolic eligibility, öz-evrilen deneyim belleği ve AGENTIC (araç-kullanımı/uzun-ufuk/all-pass) benchmark.

- **[HIGH/moderate]** Citation-graph grounding + temporal geçerlilik doğrulaması — *eksik:* ADALET'in 4-katman verify'i (L1 regex/L2 fuzzy/L2.5 Lettuce/L3 NLI) madde METNİNİN kaynakla eşleşmesini doğrular AMA: (1) maddenin yanıt-tarihinde YÜRÜRLÜKTE olup olmadığını kontrol etmez (mülga/değişik madde riski), (2) maddenin o BAĞLAMDA gerçekten ilgili olup olmadığını eş-atıf ağıyla teyit etmez — sadece metin-örtüşmesine bakar. Türkçe için Yargıtay kararlarındaki madde-atıf grafı (hangi karar hangi maddeyi birlikte anar) kurulabilir; corpus zaten 83K Yargıtay kararı. — *kaynak:* https://arxiv.org/html/2606.00898
- **[MEDIUM/hard]** Citation-faithfulness DPO (lokal-model uyumlu, anotasyonsuz) — *eksik:* ADALET verify'i RUNTIME filtre (reddet/yeniden-dene) yapıyor ama üretici LLM (Qwen) atıf-sadakatini ÖĞRENMİYOR — her seferinde aynı hatayı yapıp verify'a yakalanıyor (latency+retry maliyeti). ADALET'in zaten Qwen lokal + hallucination_gold(104) + verify_gold(31) altyapısı var; bozma-stratejileriyle DPO tercih-seti üretip lokal Qwen'i 'doğru-madde-atfı' yönünde hizalamak verify-öncesi hata oranını düşürür. Kırmızı çizgilere (lokal model) uyumlu. — *kaynak:* https://arxiv.org/html/2606.00898
- **[HIGH/hard]** Formal/sembolik doğrulanabilir akıl yürütme (statutory hesap) — *eksik:* ADALET'in bilinen KRİTİK açığı 'duration-eligibility hallucination' (örn. '2 yıl kıdem yetersiz' gibi yanlış sayısal çıkarım; MEMORY'de işaretli). Risk_guard veto detektörleri (negative_eligibility) yardımcı ama bunlar METİN-ÖRÜNTÜ tabanlı, gerçek HESAP yapmıyor. Eligibility node'u var (default OFF). Sayısal-eşikli hükümler için küçük bir sembolik-kural motoru (kıdem süresi≥X→hak doğar, faiz oranı=Y) ontoloji-şemasıyla bağlanırsa eşik-çıkarımı LLM'den alınıp deterministik+doğrulanabilir hale gelir. — *kaynak:* https://arxiv.org/pdf/2509.00710
- **[MEDIUM/moderate]** Öz-evrilen ajanlar: deneyim/dava/kural belleği (cross-case learning) — *eksik:* ADALET'in Debate ajanı Constitutional pass/retry/reject yapıyor (MAX_RETRY=3) AMA EPISODE-İÇİ — davalar arası ÖĞRENME yok. Her sorgu sıfırdan başlar; geçmiş başarılı/başarısız doğrulama desenleri biriktirilmiyor. Düşük-riskli bir başlangıç: verify-FAIL olan iddia desenlerini (hangi madde-tipi/domain kombinasyonu sık reddediliyor) kalıcı bir 'reflection store'da toplayıp draft-prompt'una few-shot olarak beslemek — kırmızı çizgi ihlali yok (kaynaksız iddia hâlâ reddedilir), latency'yi düşürebilir. — *kaynak:* https://arxiv.org/html/2408.08089v1
- **[HIGH/moderate]** Agentic benchmark: araç-kullanımı + uzun-ufuk + all-pass rubric değerlendirme — *eksik:* ADALET'in eval'i ÇOK GÜÇLÜ ama ÇIKTI-ODAKLI gold-set (hallucination 104, eligibility 46, verify 31, NLI 28) — yani 'son cevap doğru mu'. AGENTIC ölçüm YOK: (1) ajanların DOĞRU ARACI/MCP'yi çağırıp çağırmadığı (tool-use progress-rate), (2) çoklu-ajan koordinasyon hata-modları (cascading/context-loss) ölçülmüyor, (3) çok-adımlı uzun-ufuk görevde all-pass rubric değerlendirmesi yok. MASLegalBench tarzı 'her ara-adım doğru mu' ve Harvey-LAB tarzı 'tüm rubric kriterleri geçti mi' Türkçe-sivil-8-alan için kurulabilir — Teknofest/paper için ayırt edici katkı. — *kaynak:* https://aclanthology.org/2025.acl-long.116/
- **[MEDIUM/moderate]** Çoklu-ajan koordinasyon hata-modu izleme (info-cascading / context-loss) — *eksik:* ADALET 8-ajanı LangGraph state-graph'ta zincirliyor (Triaj→Mevzuat/Emsal→Draft→Verify→Debate→Finalize) ama AJAN-ARASI HATA YAYILIMINI ölçen bir mekanizma yok: örn. Triaj yanlış domain verdiğinde Mevzuat/Emsal hatalı korpustan getirir ve bu Verify'a kadar sessizce taşınır (cascading). Resilience fan-in guard VAR ama bu kullanılabilirlik için, MANTIKSAL tutarlılık için değil. Hafif bir 'inter-agent consistency check' (Triaj-domain ↔ getirilen-doc-domain uyumu, Draft-iddia ↔ Emsal-mahkeme uyumu) eklemek cascading hatayı erken yakalar. — *kaynak:* https://arxiv.org/pdf/2509.24922
- **[LOW/hard]** Öğrenilmiş ödül-modeli ile çıktı öz-değerlendirmesi (boss/judge agent) — *eksik:* ADALET'in Debate ajanı Constitutional-AI prompt-tabanlı pass/retry/reject yapıyor (KURAL-tabanlı), öğrenilmiş ödül modeli yok. ADALET'in 'LLM-as-judge' yerine deterministik verify'a yatırım yapması KIRMIZI-ÇİZGİ açısından DOĞRU (sıfır-halüsinasyon). Ancak verify-GEÇEN cevaplar arasında KALİTE sıralaması (yararlılık/eksiksizlik) için hafif bir öğrenilmiş skorlayıcı (mevcut verify_gold/hallucination_gold sinyalleriyle eğitilmiş, DISPLAY-only, verify'ı override ETMEYEN — Tahmin ajanındaki 0.85-cap deseni gibi) draft-retry'ı kalite yönünde yönlendirebilir. — *kaynak:* https://arxiv.org/html/2407.16252v1
- **[MEDIUM/easy]** Doğrudan TR ticari rakip kıyas-konumlandırması (Mevzuat AI) — *eksik:* Bu bir teknik-açık değil, KONUMLANDIRMA açığı: Mevzuat AI avukat-odaklı/kapalı-kaynak/muhtemelen bulut-LLM; ADALET'in ayırt edici tezi VATANDAŞ-odaklı + LOKAL-model + SIFIR-halüsinasyon-fail-closed + açık-kaynak. ADALET'in paper/Teknofest sunumunda bu farkı (citizen-access + verifiable + local + civil-only-safe-scope) explicit benchmark'la göstermesi gerekir; aksi halde 'mevcut TR araçlarından farkı ne' sorusu zayıf kalır. Eksik: ADALET'i Mevzuat AI ve genel LLM'lere (ChatGPT/Gemini) karşı aynı TR-sivil test-setinde citation-faithfulness + temporal-validity + scope-refusal ekseninde kıyaslayan tablo. — *kaynak:* https://mevzuat.ai/en/

### retrieval-sota
2024-2026 retrieval SOTA'sının beş ana ekseni var. (1) RERANKER: çapraz-kodlayıcı yerini "instruction-tuned LLM reranker"lara bırakıyor — Qwen3-Reranker (0.6B/4B/8B, Apache-2.0, 100+ dil, 32k bağlam) ve Jina-reranker-v3 / zerank gibi modeller MTEB-R/MMTEB-R'de bge-reranker-v2-m3'ü açık ara geçiyor; 0.6B varyantı GGUF/llama.cpp ile lokal çalışabiliyor (KIRMIZI-ÇİZGİ uyumlu). (2) EMBEDDING: Qwen3-Embedding-8B Haziran-2025'te MTEB-multilingual lideri (70.58 vs BGE-M3 63.0); Matryoshka boyut (32-4096) ve talimat-koşullu sorgu destekli. (3) GEÇ-ETKİLEŞİM (late-interaction): MUVERA (Google, NeurIPS-2024) çok-vektörü tek-vektöre indirip MIPS ile PLAID'e göre ~%90 daha düşük gecikme + ort. %10 daha iyi recall sağlıyor; TurkColBERT (newmindai — Mursit'in YAPIMCISI, Kasım-2025) Türkçe geç-etkileşim modelleri (ColmmBERT-base-TR) sunuyor: dense'ten 3-5× küçük ama +%13.8 mAP, MUVERA ile PLAID'ten 3.3× hızlı. (4) BAĞLAMSAL RAG: Anthropic Contextual Retrieval (her chunk'a LLM ile üretilmiş belge-bağlamı önekleme + prompt-caching ile ~$1.02/M token) recall@20 hata oranını %49 (BM25 ile) ve rerank eklenince %67 düşürüyor. (5) GRAPH/AGENTIC RAG: Microsoft LazyGraphRAG ön-indeksleme maliyetini full-GraphRAG'in %0.1'ine indirip vektör-RAG maliyetiyle çalışıyor; agentic RAG (sorgu ayrıştırma + öz-düzeltme) çok-adımlı sorularda statik RAG'a göre büyük doğruluk artışı veriyor. ADALET'in hybrid+RRF+ColBERT+CE-rerank hattı 2024 SOTA'sına denk; ana fırsatlar TurkColBERT/Qwen3-reranker swap'i, contextual-context önekleme ve MUVERA ile ColBERT gecikmesinin düşürülmesi.

- **[HIGH/moderate]** Bağlamsal retrieval (chunk'a LLM-üretimi belge-bağlamı önekleme) — *eksik:* ADALET seed pipeline'ı (scripts/seed/pipeline.py, chunker.py) chunk'ları HAM metinden böler; metadata (kanun_adi/title/chamber/madde_no) payload'a yazılır ama embed edilen METNE belge-düzeyi bağlam ÖNEKLENMEZ. Özellikle uzun-madde alt-chunk'larında ('VUK 359/b' gibi fıkra) ve karar gerekçe/sonuç chunk'larında bağlam izolasyonu yaşanıyor — bu tam Anthropic'in çözdüğü problem. ADALET'in lokal Qwen'i zaten var → contextual-context üretimi BULUT LLM gerektirmez, kırmızı-çizgi ihlali yok. — *kaynak:* https://www.anthropic.com/news/contextual-retrieval
- **[MEDIUM/moderate]** TurkColBERT — Türkçe geç-etkileşim modeli (ColmmBERT-base-TR) — *eksik:* ADALET'in ColBERT katmanı GENEL-amaçlı BGE-M3'ün ColBERT-vec'lerini kullanıyor (multilingual, Türkçe-hukuk için optimize DEĞİL). TurkColBERT modelleri Türkçe-native ve aynı ekibin Mursit'iyle uyumlu. ADALET'in stored-ColBERT MAX_SIM altyapısı (adalet_law_colbert collection + PyLate uyumlu) zaten kurulu → ColmmBERT-base-TR'yi ColBERT-rerank embedder olarak takmak görece düşük-riskli A/B. UYARI: TurkColBERT legal domain'i KAPSAMAMIŞ (paper'da 'future work') → madde-recall'da kazanç ÖLÇÜLMELİ (BASE-bge daha önce tr-legal-reranker'ı yenmişti, aynı durum çıkabilir). — *kaynak:* https://arxiv.org/abs/2511.16528
- **[MEDIUM/hard]** MUVERA — çok-vektör retrieval'ı tek-vektöre indirgeme (ColBERT gecikme çözümü) — *eksik:* ADALET ColBERT gecikme sorununu 'stored-ColBERT' (yan adalet_law_colbert collection'da Qdrant MAX_SIM) ile 27s→11-13s'ye düşürdü — ama bu hâlâ PLAID-tarzı çok-vektör arama. MUVERA FDE yaklaşımı bunu tek-vektör araması yapıp Qdrant'ın standart HNSW'sini kullanabilir → ColBERT-rerank gecikmesini daha da düşürüp ölçeklenebilir kılar. Qdrant ve PyLate MUVERA'yı desteklemeye başladı. — *kaynak:* https://arxiv.org/abs/2405.19504
- **[MEDIUM/easy]** Qwen3-Reranker — instruction-tuned lokal reranker (bge-reranker-v2-m3 ardılı) — *eksik:* ADALET cross-encoder olarak bge-reranker-v2-m3 (568M, 2024) kullanıyor. Qwen3-Reranker-0.6B benzer boyutta ama daha güncel + talimat-koşullu — özellikle 'doğru kanunu buluyor ama doğru MADDE'yi seçemiyor (kanun@5=82%, madde@5=37%)' problemine talimat-prompt ile saldırılabilir. Mevcut RERANKER_MODEL env-knob'ı zaten var → swap kolay; ama BASE-bge daha önce tr-legal-reranker'ı YENDİĞİ için Qwen3-reranker'ın madde-recall'da gerçek kazanç verip vermediği ÖLÇÜLMELİ (kullanıcı GPU/Qdrant ile). — *kaynak:* https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- **[LOW/moderate]** Qwen3-Embedding — Matryoshka + talimat-koşullu dense embedder — *eksik:* ADALET dense için Mursit-Base-TR (768-dim, Türkçe-hukuk fine-tuned) + sparse için BGE-M3 kullanıyor. Mursit Türkçe-hukuka özgü olduğu için genel MTEB'de Qwen3 üstün olsa da hukuk-domain'inde Mursit kazanmış olabilir (kanun@5 +7pp ölçüldü). Yine de Qwen3-Embedding-0.6B'nin Türkçe-hukuk benchmark'ında (eval_run v2 186 vaka) Mursit'e karşı A/B'si DEĞERLİ — embedding swap zaten EMBEDDING_MODEL env-knob'ıyla destekleniyor, ama kullanıcı-runtime (GPU/reseed) gerektirir. — *kaynak:* https://github.com/QwenLM/Qwen3-Embedding
- **[MEDIUM/moderate]** Mecellem — Türkçe hukuk-domain embedding + reranker (newmindai) — *eksik:* ADALET hâlâ Mursit-Base-TR (önceki nesil) kullanıyor. Aynı ekibin daha yeni hukuk-spesifik Mecellem reranker'ı (genel bge-reranker-v2-m3 yerine) madde-disambiguation'da kazanç verebilir — çünkü Türkçe-HUKUK'a özgü eğitilmiş (genel TurkColBERT'in eksiği olan legal-coverage burada VAR). RERANKER_MODEL/EMBEDDING_MODEL env-knob'larıyla takılabilir; gerçek kazanç eval_run v2 + verify_gold ile ÖLÇÜLMELİ. HuggingFace erişilebilirliği paper repo-linkinden teyit edilmeli. — *kaynak:* https://arxiv.org/abs/2601.16018
- **[LOW/hard]** LazyGraphRAG — sorgu-anı graph+vektör füzyonu (ön-indeksleme maliyeti sıfır) — *eksik:* ADALET'te GraphRAG VAR (graph_rag.py, NetworkX) ama default-OFF ve klasik 'önce-graph-kur' yaklaşımı — offline build_graph.py gerektiriyor, in-memory yükleniyor, k-hop BFS yapıyor. LazyGraphRAG'in 'sorgu-anı vektör+graph füzyonu, tembel-LLM' tasarımı ADALET'in mevcut hybrid-retrieval'ına graph-kenarlarını sorgu-anında bindirip pahalı offline graph-summary'den kurtarabilir. Hukukun ilişkisel doğası (case CITES law GOVERNS concept) bu yaklaşıma uygun. Ancak ADALET'in zaten çalışan GraphRAG'i var → bu bir 'mimari iyileştirme', sıfırdan-ekleme değil; öncelik düşük. — *kaynak:* https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/

### competition-product
2024-2026 legal-AI dünya-standardı net bir tezde toplanıyor: "verifiability-by-design + attorney-oversight + agentic provenance trace + domain-specific eval". Harvey (~0.2% halüsinasyon iddiası, custom case-law modeli %97 tercih), Thomson Reuters CoCounsel (her gece 1500+ test/skill, "LLM-as-judge" law-school-exam grading, ISO/IEC 42001 sertifikası, kapalı-trusted-corpus guardrail) ve Spellbook (clause benchmark kütüphanesi, audit-trail, zero-retention) artık YARIŞMIYOR; "trust deciding factor" diyorlar: her iddianın kaynağa kadar izlenebilirliği, ara-adımların görünür "thinking states" ile denetlenmesi, insanın her adımda müdahale/override edebilmesi ve "fewer checkpoints"i RİSK sinyali olarak çerçevelemek. Akademide generic RAG metrikleri (Ragas) yerine legal-domain LLM-as-judge yükseliyor (LeMAJ — "Legal Data Points" ayrıştırması, uzman-yargısıyla yüksek korelasyon). Açık-kaynak ekosistemi (CourtListener-MCP citation-verification, Eyecite citation-extraction, lawglance RAG, awesome-legaltech) citation-provenance + plain-language + guided-intake + multi-jurisdiction'ı standart bekleniyor sayıyor. Türkiye'de ürün ortamı: Lexpera-Lexi/LexChat/Hukuk.ai/HukukChat hep PROFESYONEL (avukat) odaklı, citation/güven-UI zayıf, vatandaş açığını doldurmuyor; Adalet Bakanlığı resmi "vatandaş dilekçe asistanı" (kira/nafaka/icra) duyurdu ve 78 baro karşı çıktı + bir "AI yanlış-yönlendirme skandalı" haberi var — yani güven/halüsinasyon-kalkanı bir vatandaş-aracında EN KRİTİK farklılaştırıcı. Yarışma tarafı: Teknofest TDDİ kapalı-kaynak API ve ücretli yazılım kullanımını YASAKLIYOR (ADALET'in lokal-Qwen/Whisper/Coqui mimarisi birebir uyumlu = otomatik avantaj), açık-kaynak lisans zorunlu; finalde jüri kodtan çok proje-hakimiyeti + canlı demo + savunmaya bakıyor. TÜBİTAK 2209-A ise ölçülebilir başarı kriterleri + iş-zaman çizelgesi + formal-uyum istiyor (ADALET'in scorecard/Wilson-CI eval altyapısı bu beklentiyle örtüşür ama proje-önerisi metnine henüz çevrilmemiş).

- **[CRITICAL/moderate]** Per-claim provenance trace UI (her iddia → tıklanır kaynak + ara-adım izi) — *eksik:* ADALET backend'de verify L1-L3 + risk_guard + _filter_to_verified ile iddiayı zaten DOĞRULUYOR ve AgentFlowGraph ile node-akışını gösteriyor; ama frontend'de bireysel cümle/iddia düzeyinde 'bu cümle şu Madde/karardan, fuzzy=0.x, NLI=ent' şeklinde TIKLANIR inline-citation + kaynak-türü rozeti (mevzuat vs emsal vs model) yüzeyi yok. Verify kararı kullanıcıya 'neden güvenilir' olarak görünmüyor — sadece sonuç görünüyor. — *kaynak:* https://www.harvey.ai/blog/how-we-approach-design-at-harvey , https://www.harvey.ai/blog/integrating-deep-research-into-harvey
- **[HIGH/moderate]** Legal-domain LLM-as-judge değerlendirme (Ragas üstü), uzman-korelasyonlu — *eksik:* ADALET'in scorecard.py + Wilson-CI + verify_gold(F1=0.93) + hallucination-gold(P/R=1.0) altyapısı GÜÇLÜ ama bunlar çoğunlukla ikili grounding/halüsinasyon-yakalama metrikleri; 'cevap hukuken EKSIKSIZ mi, doğru otoriteyi doğru mu uyguluyor, vatandaşa actionable mı' boyutunu ölçen legal-LLM-as-judge (Legal Data Points decomposition) harness'i yok. Bu, jüri ve paper için 'biz Ragas'tan öteye geçtik' kanıtı sağlar. — *kaynak:* https://aclanthology.org/2025.nllp-1.23.pdf , https://legal.thomsonreuters.com/blog/why-your-legal-ai-needs-more-than-the-open-web-a-look-inside-cocounsels-guardrails/
- **[HIGH/easy]** Lokal/açık-kaynak mimarinin yarışma-kuralı diferansiyeli olarak öne çıkarılması — *eksik:* ADALET teknik olarak ZATEN uyumlu (lokal model, MIT lisans) — ama bu, sunum/proje-önerisinde açık bir 'yarışma-kuralı-uyum + reprodüksiyonel-bilim + maliyet-bağımsızlık + veri-egemenliği' DİFERANSİYELİ olarak paketlenmemiş. Rakip Türkçe ürünler (Lexpera/LexChat) kapalı-bulut; resmi UYAP-AI da kapalı. Bu, jüriye 'tek açık-kaynak + tek tam-lokal + tek doğrulamalı' üçlü konumu vermek için kanıtlanabilir bir kaldıraç. — *kaynak:* https://www.teknofest.org/tr/yarismalar/turkce-dogal-dil-isleme-yarismasi/ , https://cdn.teknofest.org/media/upload/userFormUpload/Turkce_Dogal_Dil_Isleme_Teknik-Sartname_OIvDn.pdf
- **[HIGH/moderate]** Açık halüsinasyon-oranı + güven kalibrasyonu kamu-rakamı (trust headline metric) — *eksik:* ADALET'in iç metrikleri (verify F1=0.93, hallucination-gold P=1.0/R=1.0, veto-FP=0) bu manşetlerden DAHA güçlü ama 'ADALET halüsinasyon oranı: %X (N=104 gold, %95 Wilson CI)' gibi TEK yarışma/landing manşeti olarak öne çıkarılmıyor ve rakip-bulut-LLM ile kıyaslı bir 'aynı sorulara ChatGPT %Y uydurma vs ADALET %0' tablosu (eval-only, API-key gerektiren — kullanıcının koşması gereken) yok. Manşet + kıyas tablosu en güçlü 'wow' kaldıracı. — *kaynak:* https://medium.com/@takafumi.endo/how-harvey-built-trust-in-legal-ai-a-case-study-for-builders-786cc23c3b6d
- **[MEDIUM/moderate]** İnsan-denetimi/override'ı UX'te birinci-sınıf akış yapmak (human-in-the-loop) — *eksik:* ADALET'in disclaimer'ı + clarifier QUESTION_BANK'i + verify-reddi var; ama vatandaş 'bu maddeyi reddet / bu emsali bağlamıma uymuyor işaretle / şu adımı yeniden sor' diyerek akışa müdahale edip cevabı yeniden-yönlendiremiyor. Vatandaş-odaklı üründe bu 'ben kontroldeyim' hissi hem güven hem etik (Avukatlık Kanunu — tavsiye değil) için kritik; jüriye 'kullanıcı pasif tüketici değil' demanstrasyonu. — *kaynak:* https://www.harvey.ai/blog/legal-ai-oversight , https://www.spellbook.legal/
- **[CRITICAL/easy]** Vatandaş-odaklı konumlandırma + canlı-demo senaryosu (rakip-ortama karşı) — *eksik:* ADALET'in 8-sivil-alan + dilekçe + clarifier'ı teknik olarak buna hazır; eksik olan, jüri için 'gerçek vatandaş senaryosu' canlı-demo akışı (örn. 'kiramı zamanında ödedim ama tahliye ihtarı geldi' → triaj→mevzuat→emsal→doğrulanmış-cevap→dilekçe-PDF, hepsi ekranda kaynak-izli) ve resmi-UYAP/baro-tartışması karşısında 'biz halüsinasyon-kalkanı + açık-kaynak + lokal ile bu skandalın çözümüyüz' konumlandırması. Aile-hukuku (nafaka/velayet) ADALET'in kırmızı-çizgisi olduğundan resmi-projeden ETİK-olarak ayrışma da bir anlatı kaldıracı. — *kaynak:* https://www.thomsonreuters.com/en-us/posts/ai-in-courts/chatbots-pro-se-litigants/ , https://foundern.com/2026/04/adalet-bakanligi-yapay-zeka-avukatlik/
- **[MEDIUM/hard]** Citation-doğruluğunun 'kaynak hala geçerli mi' katmanı (Shepardization muadili) — *eksik:* ADALET madde/karar metnini DOĞRULUYOR ama 'bu kanun maddesi mülga mı, değişti mi; bu Yargıtay kararı içtihadı birleştirme ile değişti mi' güncellik/yürürlük katmanı yok. TR'de bu kısmen mevzuat.gov.tr 'mülga/değişik' işaretleriyle yapılabilir. Vatandaş için 'eski/yürürlükten kalkmış madde'ye dayanmak ciddi risk; bu, halüsinasyon-kalkanının doğal bir sonraki adımı (ölçülerek, yargi-mcp metaverisiyle). — *kaynak:* https://medium.com/@takafumi.endo/how-harvey-built-trust-in-legal-ai-a-case-study-for-builders-786cc23c3b6d
- **[MEDIUM/easy]** TÜBİTAK 2209-A için ölçülebilir-kriterli proje-önerisi paketi — *eksik:* ADALET'in scorecard PASS/FAIL CI-gate + Wilson-CI + gold-setleri (104/46/31/28) tam da 2209-A'nın istediği 'ölçülebilir başarı kriteri' kanıtı — ama bu eval-altyapısı henüz iş-paketi+başarı-kriteri formatında bir proje-önerisi metnine çevrilmemiş. Mevcut eval rakamları doğrudan WP-başarı-eşiklerine (örn. 'WP3: madde_recall@5 >= %X, %95 CI alt-sınır >= %Y') haritalanabilir. — *kaynak:* https://tubitak.gov.tr/en/scholarships/degree-associate-degree/destek-programlari/2209-research-project-support-programme-undergraduate-students , https://tto.ankara.edu.tr/wp-content/uploads/sites/423/2024/04/2209a_arastirma_onerisi_formu_15.03.2024_Ogr.-Gor.-Elif-Ayaz.pdf
