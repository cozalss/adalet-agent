# ADALET — Değişiklik Günlüğü

> Tüm proje geçmişinin (220 commit) temalara göre düzenlenmiş kaydı. Kronolojik değil; her temada en yeni üstte. Madde formatı: `hash` — kısa Türkçe açıklama.

---

## Çekirdek Ajan / Pipeline & Doğrulama

Çoklu-ajan orkestrasyonu (LangGraph), draft/finalize üretimi ve SIFIR-HALÜSİNASYON doğrulama katmanı.

### Doğrulama (Verify / NLI / Veto)
- `bf6c3b5` — unsourced detektör recall'unu yükselt (0.375 → 1.0)
- `b1837af` — halüsinasyon kalkanı + ölçüm (master-plan Faz-1): `fabricated_citation_claims`, `implausible_article` detektörleri, veto-FP 0/16
- `7a0682e` — SIFIR HALÜSİNASYON veto katmanı verify pipeline'a entegre
- `7cfa208` — verification cache (NLI): tekrarlı doğrulama atlanır
- `138a104` — verify çelişki vetosu için sinyal-redundansı (small-n false-positive azalt)
- `18d22d1` — verify layer1 kaynak-id formatını (m-IK-21) geçerli madde referansı say
- `e84ec42` — doğrulama: claim'in atıf yaptığı madde no'ya kanıt daraltma
- `8b5199e` — doğrulama fail-closed — VERIFY_STRICT + self_rag/finalize sızıntı kapatma
- `1cc5b09` — LettuceDetect grounding kaynağı görmüyordu (H3) → evidence-aware default
- `d1f2543` — NLI truncation `only_first` — hipotez (claim) bütünlüğünü koru
- `d587e9c` — draft system-prompt sertleştirme: citation fabrication yasağı
- `fa3c48e` — verify-katman kalibrasyon harness + altın küme ("ölç-bir-kez-değiştir")
- `df21239` — verify kalibrasyon regression-guard'ları + gold id-unique kontrolü
- `25965b8` — verify gold küme 31→59 + sağlamlık doğrulaması (8 domain)

### Pipeline / Graph / Düğümler
- `f39e6e2` — zengin avukat-ön-görüşmesi cevap formatı (önceki kısa/yapısal'dı)
- `1f4eb04` — draft kanun-adı guard (Qwen TKHK'yi "Ticaret Kanunu" diyordu)
- `2a3da7b` — multiturn t2-answer bug: clarifier cevabında domain devral (%45→%100)
- `b97f3f6` — retry artık YENİDEN RETRIEVE eder + dedup reducer (architect A1/A2)
- `650c035` — yapılandırılmış uygunluk geçişi node'u (eşik akıl yürütmesini ayır)
- `3607868` — iş hukuku akıl yürütme: triaj olgu çıkarımı + eşik-kontrollü draft
- `edad813` — draft eşik-kontrolü prompt'unu güçlendir (olguları öne al + aritmetik örnek)
- `02628a5` — finalize cümle-eleme: kısaltma-bilinçli bölme + sızıntı-önleyen düşürme
- `501209c` — pipeline sertleştirme: fail-closed coercion + kapsam-koruyan finalize
- `8d77929` — draft cevabı yapısal 5 bölüme dönüştür + finalize agresifliği gevşet
- `d931484` — draft + finalize + triaj: post-processing, citation cleanup, fact extraction
- `8f63785` — verify + retrieval: kalibrasyon-destekli eşik, mock testler, A/B harness

### Triaj & Sohbet Davranışı
- `5af2e58` — 3 batch-test problemini çöz: NLI süpermajority + triaj sertleştirme
- `d84a9ee` — triaj salvage: Çince sızıntılı / kesilmiş JSON'dan domain regex kurtar
- `05385eb` — triaj prompt'a vergi/iş ödememe ayrımı + MTV örneği
- `ce52f43` — ChatGPT benzeri konuşma deneyimi: sıcak yanıtlar + multi-turn bağlam
- `a93006f` — selamlaşma/sohbet kısa-yolu: soğuk ret yerine dostça yanıt

### Kararlılık & Eşzamanlılık
- `8ab5e4d` — llama-cpp decode yarışını kır: tek-worker executor
- `fd839d5` — context-taşma çökmesi (llama_decode -1) — 3 katmanlı koruma
- `3eb4516` — LlamaCppClient eşzamanlı model-load race → double-checked asyncio.Lock
- `a01bb05` — ajan-node hijyeni: self_rag debate_notes append + emsal except genişlet
- `cb97b19` — `/ask` + `/ask/stream` uçtan uca graph timeout (hung-graph koruması)
- `a35c31d` — SSE event sözleşmesi: intent + clarify event'leri (V2 yolları)

---

## Bilgi Erişimi (Retrieval / RAG / Reranker)

Hibrit (BM25 + dense) erişim, domain-aware embedder, Mursit koleksiyonu ve TR-hukuk reranker.

### Mursit Production & Spekülatif Retrieval
- `635e2f7` — Mursit production entegrasyonu — 10x hızlı retrieval
- `4050ae2` — domain-aware sparse embedder: vergi +36pp, P95 −42%
- `7f6b2c2` — latans garantili spekülatif retrieval — max 2.3s
- `95266e1` — dense+sparse Mursit koleksiyonu + spekülatif testler
- `dbfc110` — MursitEmbedder: dense-only 768-dim SentenceTransformer wrapper
- `afe6415` — embedding kalite testi + re-index scripti
- `371dccd` — `adalet → adalet_mursit` delta sync scripti
- `3d2e807` — domain+complexity bazlı adaptive HyDE/MQ seçimi + Mursit A/B
- `eaf25ec` — `.env.example`: Mursit + adaptive routing + spekülatif varsayılanlar

### Sıralama (Ranking / Reranker)
- `f6907de` — mevzuat sıralaması: domain-öncelikli tier-sort + cross-encoder rerank (konuşma-dili TR'de cross-encoder güvenilmez bulgusu)
- `bfd7ffc` — emsal mahkeme-öncelikli tier-sort: anayasa hacim baskısını kır
- `80adca3` — tüketici retrieval: TKHK domain-scoped arama + reseed_law script
- `237466c` — emsal source-scoped supplementary + yönetmelik kanun_kodu surface
- `c5d02f3` — reranker `max_length=512` — KATASTROFİK yavaşlık fix'i (665s→30s)
- `4ed0758` — reranker alaka eşiği (`RERANK_SCORE_MIN`) — alakasız aday eler

### Recall & A/B
- `fb3661b` — Multi-Query A/B ölçümleri + tam karşılaştırma tablosu
- `8f01351` — HyDE A/B ölçümleri + alan bazlı etkinleştirme
- `a78112d` — deterministik hukuki eşanlam genişletmesi (multi-query recall)
- `9ed5aff` — Türkçe İ/I casefolding + 4-yönlü ünlü uyumu (RAG recall)
- `f18d377` — E2E gecikme ~8-12s azaltma: paralel retrieval + SSE progress
- `db81b49` — Danıştay HTML response parse + ChunkPoint sparse_indices/values fix

### Performans (Bağlantı / Önbellek)
- `e737d48` — Qdrant bağlantı havuzu: request path için paylaşılan client
- `4b9f663` — event loop bloklamayı bitir: embedder/NLI `to_thread` + thread-safe

---

## Akıllandırma Fazları & Eval

"microGPT yerine" 5-fazlı akıllandırma master-planı ve değerlendirme harness'leri.

### Faz-2/3/4 (Triaj DistilBERT · NLI-TR · Reranker)
- `d221c82` — DistilBERT-TR triaj modeli eğitildi + kalibre (Faz-2 tamamlandı)
- `0dfa6a2` — DistilBERT-TR domain sınıflandırma kademesi (Faz-2)
- `986ac42` — NLI-TR yanlış-pozitif çelişki ölçüm harness'ı (Faz-3): eşik 0.70 measure-first ile korundu
- `ff5932b` — konuşma-dili sentezli TR-hukuk reranker fine-tune pipeline (Faz-4)
- `5844ff7` — Qwen dil-kayması guard (gerçek-Qwen demosunda yakalandı)
- `689eb16` — `warmup_ratio` → `warmup_steps` (Transformers v5 deprecation)
- `4b7624f` — 12GB GPU OOM düzeltmesi: adafactor + max_length cap (Faz-4 eğitim doğrulandı)
- `3b1ed6c` — reranker A/B değerlendirme: base vs fine-tuned pairwise (pairwise accuracy 0.873→0.952, +7.9pp; ayrım 0.38→0.71, ~2×)

### Eval Harness & Kalite Kapıları
- `e728a8b` — §4.2 verify ON/OFF ablasyon: claim-support %41.9 vs %100 (+58pt), 8 soru gerçek Qwen
- `cacbb5e` — verify ON/OFF ablation harness + edge_cases CLI + `VERIFY_ENABLED` kaldıracı
- `c317290` — prompt kalite kapısı (prompt A/B'den ÖNCE)
- `def5dc1` — prompt A/B: candidate-2 KALDI + KRİTİK halüsinasyon bulgusu
- `f565faa` — prompt A/B: candidate-1 kapıdan KALDI (gate regresyonu engelledi)
- `e46f19c` — draft kalite eval harness: Türkçe-purity + kısa-cevap + src-bağı + uzunluk
- `53c9ed6` — eval setleri büyütüldü 60→220 vaka + injection + answer setleri
- `5917818` — domain@1 metriği kanun chunk'larını adil sayar (kanun_kodu→domain)
- `9d38da8` — eval uzunluk hedefi 160-220 → 100-160 (veri-temelli)

---

## Tahmin Modeli (Predictive)

Dava-sonucu tahmini (BERT-TR 3-sınıf) — kuruluş, "silver balonu" ifşası ve LLM-relabel ile gerçek çalışan modele varış.

- `39241b3` — tahmini çıktıya bağla + veto-uyum + min-emsal guard
- `2325dbe` — Qwen tam-hüküm ile yeniden-etiketleme (silver onama/bozma fix) → gold_qwen'de accuracy 0.28→0.73, f1_macro 0.27→0.70, ECE 0.55→0.029
- `f055d7b` — temiz + tam hüküm extraction + Qwen çökme guard'ı
- `2bfc589` — gold-review'da TAM hüküm (`hukum_excerpt` 400-char kesitti)
- `6a7d19f` — hukukçu-dostu `.xlsx` gold-review (CSV okunaksızdı)
- `d5f6bc9` — GOLD eval pipeline: silver balonunu deldi (BERT 0.825→0.47 LLM-ref; tam-hüküm Qwen-ref'inde 0.2817)
- `3952c4f` — Faz-5 tamamlama: bağımsız eval harness + train/serve hizalama fix (accuracy 0.8256 / f1_macro 0.8249, ECE 0.0303)
- `2886586` — BERT-TR dava sonucu tahmin pipeline — f1_macro 0.825, ECE 0.011 (kalibre; sonradan silver-yanılsaması olduğu ölçüldü)
- `cd92091` — Tahmin ajanı (8. ajan) — dava sonucu tahmini heuristic baseline
- `966693e` — Dilekçe Ajanı (6.) + Tahmin Ajanı HÜKÜM-izolasyonu + ADR-009 BERT-TR yol haritası

---

## Frontend / UI & Erişilebilirlik

Next.js/Vite + React arayüzü, `/sor` akışı, tasarım sistemi entegrasyonu ve WCAG a11y cilası.

### `/sor` Sohbet Arayüzü & Backend Entegrasyonu
- `dd9e8f9` — premium kullanıcı avatarı: isimden türeyen gradient + gem parlaması
- `b6dd05f` — `/sor` backend entegrasyonu sağlamlaştırıldı + UI cila (batch-1)
- `4e2ad4f` — repo-ilhamı paneller: ajan-izi şeffaflık + tahmin + stick-to-bottom (batch-2)
- `0a75678` — kaynak mührü + zengin citation popover + `?preview` demo modu (batch-3b)
- `beef4ec` — OCR PII uyarısı + domain-kartı boş-durum (batch-4)
- `77a91f9` — dürüst sidebar (gizlilik-önceliği) + reset→DELETE session (batch-5)
- `f6e8a74` — editorial cevap hiyerarşisi + touch hedefleri ≥44px (batch-6)
- `f492dcb` — cevap metninde inline markdown (**kalın** / *italik*) render (batch-7)
- `b92fabd` — doğrulama aşaması SSE'de canlı: 4. stepper adımı artık ölü değil (batch-9)
- `a872698` — sidebar nav dürüstlüğü + OCR limit sabiti (batch-10)
- `d43bf5f` — kullanıcı mesajını düzenle & yeniden gönder (batch-11)
- `a85397a` — güvenlik + doğruluk sertleştirme (ECC code/security review konsolidasyon)

### Tasarım Sistemi & Etkileşim Cilası
- `b09bed8` — 6 tasarım sitesi UI entegrasyonu: motion + trust + legal tooltips
- `03f414a` — backend-frontend uyum sertleştirme (9.3→9.9/10, tur-2)
- `eb07a07` — Lucide ikon tutarlılığı + ajan pipeline ayırt edici ikonlar
- `5b902e2` — Vuetify snackbar-with-undo → "Yeni sohbet" geri-al
- `3d6ae0f` — daisyUI kbd → klavye kısayolu ipuçları (elle CSS)
- `5056dc0` — daisyUI timeline → ajan pipeline görselleştirmesi (elle CSS)
- `2a6f0e9` — daisyUI stat deseni → kanıt-özeti paneli (elle CSS)
- `587e2ce` / `37afcd4` — ui-ux-pro-max skill denetimi: a11y + etkileşim cilası (tur-1/2)
- `b2382f7` — PWA: kurulabilir uygulama + offline kabuk (NextChat ilhamı)

### Erişilebilirlik (a11y / WCAG)
- `6f30de7` — WCAG AA kontrast: navy (dark) tema proaktif düzeltme (tur-2)
- `d0f29d2` — WCAG AA kontrast: 4 başarısız renk çifti düzeltildi (tur-1)
- `5746b61` — erişilebilirlik sertleştirme: drawer focus-trap/Esc + aria-live (batch-3a)
- `365e35b` — mobil header taşması: dar ekranda Kaynaklar pill kırpılması giderildi

### Frontend Testleri (Vitest)
- `e0fd7b4` — Vitest kurulumu + ilk testler + `/me` proxy fix
- `867687f` — sohbet saf mantığını `conversationUtils`'e ayır + 17 test
- `a6d3cb9` — vitest + build pipeline ("test geçmeden ship yok")
- `3e904b7` — `parseAnswer` (SSE→UI köprüsü) — 17 test
- `d5731b1` — ui render helper'ları + legalTerms — 13 test
- `112fa19` — cards + panels bileşen render testleri — 14 test
- `04eeaa9` — hook durumsal davranış testleri (renderHook) — 13 test
- `187e7be` — `useChat` SSE durum-makinesi davranışı — 5 test
- `3080352` — kapsam raporu (`@vitest/coverage-v8`) + CI artifact
- `c3dfb63` — küçük bileşen render testleri — 9 test
- `e7f6e5b` — accountPanels + historyPanels + AuthPage render — 18 test
- `674d692` — Playwright gerçek-tarayıcı E2E + CI job
- `a425d16` — misafir kaldırılınca kırılan Playwright testlerini onar

---

## Kimlik & Veri (Auth / Supabase / DB)

KVKK kısıtının kaldırılması, ilişkisel DB katmanı ve Supabase tam geçişi (auth + sohbet geçmişi).

### Supabase Tam Geçiş (v2.2)
- `bf57030` — Supabase C2: ES256/JWKS doğrulama (HS256 secret YANLIŞTI)
- `bb7cc00` — misafir modunu kaldır: site kayıt/giriş zorunlu
- `450cf93` — DB derin-denetim sertleştirmesi (2. tur 3-ajan) + ops runbook
- `9615f42` — Supabase DB katmanını sertleştir (3-ajan incelemesi bulguları; SIGNED_OUT yerel temizleme)
- `e2acd30` — sohbet geçmişi + tercihler + dosyalar → Supabase (tam geçiş Phase B)
- `42a06ba` — Supabase Auth'a geç (Phase A): e-posta/şifre + Google + misafir
- `5797f0e` — Supabase keep-alive workflow (Free plan 7-gün inaktivite pause'unu önle)
- `a1e2984` — KVKK'yı kısıt/kırmızı-çizgi olmaktan çıkar (yük kaldırıldı, artı korundu)

### İlişkisel DB Katmanı & Hesap (önceki sürüm)
- `e6769e5` — e-posta/şifre giriş + kayıt sayfası → `/sor` (özgün)
- `45ee600` — kalıcı sohbet geçmişi + sidebar özellikleri (KVKK politikası gevşetildi)
- `d520657` — ADALET'e özgü hesap/profil menüsü — full-stack (frontend + backend + DB)
- `b0b445b` — API key Postgres repo: boot-cache, revoke desteği (auth hot-path sync)
- `f8d8837` — PostgreSQL ilişkisel DB katmanı: env-gated, repository pattern
- `87605f5` — auth hardening: API key hashing + IDOR owner binding + auth visibility

---

## Çok-Modluluk (OCR / STT / TTS / Dilekçe)

Belge OCR'dan olgu çıkarımı, sesli round-trip ve dilekçe (PDF/DOCX) üretimi.

- `71c752d` — OCR belge metninden `case_facts` çıkarımı (clarifier yükü azalır)
- `33dcbcd` — editlenebilir `.docx` dilekçe çıktısı — PDF ile paralel
- `5c9bcfd` — Docker `uv.lock` güncelle: jinja2 + reportlab (Dilekçe Ajanı deps)
- `bc90848` — TTS→STT round-trip'i pipeline-bütünlüğü assertion'ına çevir (flaky fix)
- `7469182` — flaky TTS→STT round-trip assertion'ını ASR-dayanıklı köke çek
- `336e219` — multimodal hata string'lerinde info-disclosure sızıntısını kapat

---

## Veri Tohumlama (Seed / Corpus)

Mevzuat, Yargıtay/Danıştay emsal ve HuggingFace korpus tohumlama hatları.

- `1f75569` — Danıştay vergi/idari seed + hybrid delta sync düzeltmesi
- `e6378fd` — vergi/idari domain Danıştay eklendi + sync TARGET env'den oku
- `49a4216` — Danıştay HF seed: idari + vergi domain takviyesi
- `d34deb5` — yönetmelik + direct Yargıtay seed pipeline'ları
- `4747cac` — HuggingFace Turkish-Law-Documents-700k seed pipeline
- `8f83f03` — UYAP emsal + GİB özelge entegrasyonu — 5 domain veri güçlendirme
- `53aebfb` — GİB özelge per-kanun seed yapısı + `_consume` refactor
- `f9f030b` — UYAP date params + GİB özelge keyword genişletme
- `b61fa2e` — iş hukuku retrieval: kıdem dayanağı (EIK m.14) seed + çapa-madde garantisi
- `ea19f29` — seed 429 rate-limit için exponential backoff (10s/30s/60s)
- `3bbd9c8` / `bed573a` — seed/refresh CLI Windows crash: pyarrow native preload

---

## Güvenlik & Gözlemlenebilirlik & Ops

Üretim sertleştirmesi, Prometheus/structlog metrikleri, latans ölçümü, CI ve tek-komut deploy.

### Güvenlik Sertleştirme
- `c0262cc` — E2E bypass staging guard: `?e2e=1` yalnız localhost'ta (MEDIUM)
- `5b82956` — 7-ajan denetim remediation: 2 CRITICAL + 2 HIGH + MEDIUM/LOW
- `3ff9f8f` — audit PII-hash + IDOR fail-closed + user_meta DoS guard + STT magic-byte + fetch_maddeler N+1 + CI sert kapı
- `2ac90c1` — production hardening: security headers, PII-log fix, OCR/upload güvenliği
- `16ef9f8` — invite endpoint rate-limit: davet kodu brute-force/enumerasyon koruması
- `2c03238` — auth/feedback bloklayan dosya I/O → `to_thread` + invite TOCTOU kapatma
- `f30264f` — API-key timing-safe karşılaştırma + conversation_id format validation
- `9c66ba6` — assert-as-guard → açık RuntimeError (`python -O` production güvenliği)
- `984d6f1` — iç hata detaylarını istemciye sızdırmayı kes (info disclosure)
- `10fd177` / `d5cb9a9` — PII maskeleme: `principal.sub` fingerprint + log redaksiyon nested

### Gözlemlenebilirlik & Latans
- `d569f27` — Prometheus `/metrics` exposition + verify/finalize timing
- `3137507` — tek-tap structlog → metrics aggregator (tüm yollar)
- `324f525` — `/metrics/latency` P95/P99 endpoint + 320 token bilinçli karar
- `916d67d` — içerik-risk detektörü + gerçek halüsinasyon ölçümü
- `2590ef3` — LLM token bütçesi A/B + truncation detektörü
- `32c83c4` — retry yolu latans ölçümü + kritik default-config bulgusu
- `51af8f1` — SSE stage latency event + `latency_profile` avg bug fix
- `76cb321` — spekülatif wall-clock bug + koleksiyon tek-doğru-kaynak + P95/P99 harness

### LLM Performans & Deploy
- `f43f495` — kayıpsız hızlandırma: prompt-lookup speculative decoding + flash_attn
- `84029e4` — yerel Qwen GPU yüklemesi (torch CUDA DLL) + draft Türkçe-only kuralı
- `eb2fca2` — Windows native crash: pyarrow'u torch'tan önce yükle (embedder/reranker unblock)
- `7082dc5` — request-path singleton'ları lifespan'de eager warm-up
- `0d57a7b` — tek-komut production compose (Caddy TLS + llama-server GPU profili) + `.env.example`
- `f9fc2d3` — onboarding quickstart: bootstrap.ps1 + dev compose + README

### CI / Lint / Tip
- `6765363` — CI: Node 22 (pnpm 11.5 `node:sqlite` → Node ≥22.13)
- `5f527db` — main.py import sırası (ruff I001) — CI yeşil
- `2eb969c` — mypy 21 tip hatası sıfırlandı (CI type-check)
- `585837d` — CI geçişi: bandit HIGH + ruff 44 hata sıfırlandı
- `1f15aea` — pip-audit yeşil: lxml 6.0.4→6.1.1 (PYSEC-2026-87) + diskcache ignore-vuln
- `a89d034` — release hygiene: ruff + mypy + bandit hepsi yeşil
- `83aec5e` — mypy dict type-arg + V2 kaynak/test konsolidasyonu (yeşil ağaç)
- `c592d10` — lint: B023 closure bug + E501 + I001 import sort
- `98d8937` / `685eb7c` — strict mypy temizliği + pytest/ruff/mypy `--extra dev`
- `9d66542` / `a85f38f` — bandit B615/B301 skip + pyproject config (.venv hariç)
- `10399a4` — `actions:write` permission (GHA cache için zorunlu)
- `4c3dff6` / `6aa7052` — docker disk-full düzeltme + build smoke timeout 15→30dk
- `02be846` — critic findings: lint clean + 4 production correctness bug
- `d680120` — kod hijyeni 8 → 10 push
- `29db848` — izole feedback writes: conftest autouse fixture + gitignore
- `7da659f` — `configure_logging` fail-loud + retry/sink invariant belgesi
- `0b80d86` — MCP kod tekrarını tek kaynağa topla (`mcp_base.py`)

---

## Dokümantasyon

README, mimari, eval/ablation ve tez artifact'leri.

- `1796e83` — README Teşekkür bölümü kaldırıldı (Lisans korundu)
- `90976c1` — README sıfırdan yeniden yazım (3-ajan denetimli)
- `304fc7d` — README kapsamlı yeniden yazım: ChatGPT karşılaştırma + örnek istek/yanıt + 4-katman verify + tahmin + production + API tablosu
- `000d3db` — README V2 karar katmanı + doğrulanmış metrikler
- `3eb0961` — tüm md dosyaları güncel duruma + README görsel yenileme
- `f71b440` — metrik güncel (705 test/227 mypy) + tahmin 0.825 + 8-domain scope + production rehberi
- `49e3bdc` — V2 mimari: Policy Engine + Clarifier + Composer
- `e3df4a2` — final benchmark tablosu + Bulgu 5-7 (Mursit, adaptive routing, spekülatif)
- `48f2002` — tez: ölçülmüş sonuçlar artifact'i (gerçek retrieval + corpus metrikleri)
- `2d5ccc5` — yarışma/hibe başvuru özeti (TÜBİTAK 2209-A, Teknofest)
- `b31a6c3` — frontend `TESTING.md`: test altyapısı rehberi
- `eaf25ec` — `.env.example` (çok-modluluk/ops ile paylaşımlı)

---

## Temel Altyapı & Kilometre Taşları

- `521ad64` — Sprint-5 + Sprint-6 bridge: data expansion + multimodal real + observability
- `a346b5c` — Sprint-4 W1-W10 tamamlandı: 336 test, %83 kapsam, prod-ready
- `1e9815f` — uçtan uca data pipeline çalışır hale getirildi
- `d900f22` — proje iskeleti kuruldu
- `5bba847` — Initial commit

---

İlgili dosyalar: `c:\Users\cemmo\Desktop\Ders\adalet-agent` (kök repo), tam commit listesi için `git -C "c:/Users/cemmo/Desktop/Ders/adalet-agent" log --oneline`.
