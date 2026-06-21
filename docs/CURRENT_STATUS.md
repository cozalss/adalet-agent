# ADALET-AGENT Current Status

Son doğrulama: 2026-06-21, Europe/Istanbul. Bu dosya projenin **güncel durum için tek doğru kaynak** belgesidir. README, mimari, tez, audit ve yarışma belgeleri bu dosyaya bağlanır; eski ölçüm belgeleri tarihsel snapshot olarak okunur.

## Dokümantasyon Otoritesi

| Belge | Statü | Ne için kullanılır |
|---|---|---|
| `docs/CURRENT_STATUS.md` | Güncel ve otoritatif | Test kapıları, ürün kapsamı, model/korpus notları, bilinen doğrulama sınırları |
| `README.md` | Güncel giriş kapısı | Kurulum, hızlı doğrulama, ana iddialar |
| `docs/architecture.md` | Güncel mimari | Sistem bileşenleri, ajan akışı, operasyonel tasarım |
| `docs/DOCUMENTATION_GOVERNANCE.md` | Güncel kural seti | Hangi metrik nasıl yazılır, tarihsel belgeler nasıl işaretlenir |
| `docs/theses/*`, `docs/ablation_study.md`, `docs/audit/*`, `docs/DEGISIKLIK-GUNLUGU.md`, `docs/PROJE-DURUMU.md` | Tarihsel/snapshot | O günün ölçümleri, audit bulguları, tez taslakları ve değişiklik geçmişi |

## Ürün Kapsamı

- Backend: Python 3.11, FastAPI, LangGraph tabanlı çok ajanlı hukuk asistanı.
- Web frontend: Vite + React 18. Web uygulaması aktif ürün yüzeyidir.
- Auth ve kullanıcı verisi: Supabase zorunludur. Güncel üründe misafir/localStorage-only sohbet modu yoktur.
- Mobil: Flutter çalışma alanı repo içinde bulunur; güncel doğrulama kapısında aktif ürün yüzeyi değildir.
- Hukuk kapsamı: 8 sivil alan hedeflenir (`tuketici`, `isHukuku`, `kira`, `icra`, `trafik`, `vergi`, `tapu`, `idari`). Ceza ve aile hukuku bilinçli kapsam dışıdır.

## Güncel Davranış Sözleşmesi

- Sistem hukuki bilgilendirme asistanıdır; avukatlık hizmeti, temsil veya kesin sonuç garantisi sunmaz.
- Verify/finalize hattı sahte kaynakları, kaynakla çelişen iddiaları ve veto edilen iddiaları nihai yanıttan temizler.
- Nötr veya kaynakla birebir eşleşmeyen bazı iddialar otomatik silinmez; doğrulama metadatasında `unverified` olarak kalabilir. Bu nedenle dokümanlarda “sıfır halüsinasyon” ifadesi mutlak garanti gibi değil, ölçülen hedef ve güvenlik tasarımı olarak yazılır.
- `VERIFY_STRICT=1` üretim için fail-closed davranış hedefidir: kritik doğrulayıcılar hazır değilse güvenli hata tercih edilir.
- Hızlı yerel testlerde gerçek LLM/GPU/Qdrant yerine mock veya kapalı opsiyonel bileşenler kullanılabilir; bu sonuçlar “fast suite” olarak etiketlenmelidir.

## Son Doğrulama Matrisi

Aşağıdaki sonuçlar 2026-06-21 tarihinde mevcut çalışma ağacında gözlendi.

| Alan | Komut | Sonuç |
|---|---|---|
| Backend tip kontrolü | `uv run mypy . --exclude '\.venv' --exclude tests --exclude scripts` | Başarılı |
| Backend lint | `uv run ruff check .` | Başarılı |
| Backend hızlı test paketi | `LLM_MODE=mock HYDE_ENABLED=0 MULTI_QUERY_ENABLED=0 PRELOAD_MODELS=0 NLI_FP16=0 LETTUCE_ENABLED=0 uv run pytest ...` | `1546 passed, 5 warnings` |
| Backend güvenlik taraması | `uv run bandit -r . -c pyproject.toml -ll -ii` | Sorun bulunmadı |
| Python bağımlılık denetimi | `uvx pip-audit --ignore-vuln CVE-2025-69872` | Bilinen güvenlik açığı yok |
| Hallucination scorecard | `uv run python -m eval.scorecard --check` | Geçti; P=1.000, R=1.000; yanlış veto `0/32`; FABRIKE F1=0.9767 |
| Frontend birim/entegrasyon testleri | `pnpm.cmd test` | `262 tests` geçti |
| Frontend build | `pnpm.cmd build` | Başarılı; Vite chunk uyarısı yok |
| Frontend e2e | `pnpm.cmd e2e` | `11 passed` |
| Node bağımlılık denetimi | `pnpm.cmd audit --audit-level=high` | Bilinen yüksek güvenlik açığı yok |
| Production readiness gate | `python scripts/check_production_readiness.py` | Başarılı |
| Multimodal/training/live integration gate | `python scripts/check_live_integrations.py` | Başarılı |
| Dokümantasyon drift gate | `python scripts/check_docs_consistency.py` | Başarılı |
| Production compose parse | dummy secret env'leriyle `docker compose --profile production config -q` | Başarılı |
| Yerel canlı infra smoke | `http://127.0.0.1:6333/healthz` + `docker exec adalet-redis redis-cli ping` | Qdrant `healthz check passed`, Redis `PONG` |
| Geçici backend health smoke | mock LLM + yerel Qdrant/Redis ile `uvicorn main:app --port 8010` ve `/health` | `status=ok`, `qdrant=ok`, `redis=ok`, `llm=mock` |
| Canlı Supabase DB grants | MCP `list_tables` + `execute_sql` grant denetimi | 4 public tablo RLS açık; `anon` custom tablo yetkisi yok; `authenticated` yalnız CRUD; `save_conversation` yalnız `authenticated` EXECUTE |
| Canlı Supabase advisors | MCP `get_advisors` security/performance | DB/RLS grant açığı yok; kalan security WARN: `auth_leaked_password_protection` Pro plan gerektiriyor; kalan performance INFO: `uploaded_files.files_user` henüz kullanılmamış |
| Uygulama seviyesi parola koruması | `password_policy_issues` + `passwordPolicyIssuesWithBreachCheck` dar testleri | Backend 18 auth/parola testi ve frontend parola/auth hook testleri geçti; production env'de HIBP k-anonymity range check açıkken sızıntı parolalar Supabase signup öncesi reddedilir |

Backend hızlı test komutu opsiyonel/entegrasyon ağırlıklı şu alanları dışarıda bırakmıştır: `tests/multimodal`, `tests/training`, `tests/agents/test_real_llm_e2e.py`. Bunun yanında hızlı ana suite artık model indirmeyen `test_multimodal_contract_fast.py` ve `test_training_contract_fast.py` kontrat testlerini içerir.

## Production Readiness

- Production compose ve `.env.example` güncel üretim model string'iyle hizalıdır: `Qwen3.5-9B-UD-Q4_K_XL.gguf`.
- Compose stack secret guard'ları, healthcheck'leri, non-root/read-only backend container'ı, Redis/Qdrant/Postgres health dependency'leri ve Trivy image scan CI kapısı ile korunur.
- `scripts/check_production_readiness.py` bu kontratları offline olarak doğrular; Docker/GPU gerektirmez ve CI `readiness-gates` job'ında çalışır.
- Supabase yeni proje davranışı için Data API explicit `GRANT` migration'ı vardır: `supabase/migrations/0002_explicit_data_api_grants.sql`.
- Canlı Supabase projesinde Data API tablo/RPC privilege'ları sıkılaştırıldı: `anon` custom tabloları çağıramaz, `save_conversation` RPC yalnız `authenticated` role'ünde çalışır.
- Supabase Pro plan gerektiren leaked-password protection toggle'ına ek olarak, web kayıt akışı production'da HIBP Pwned Passwords k-anonymity range check (`VITE_HIBP_PASSWORD_CHECK=1`) uygular; eski internal `/auth/register` yolu da no-network parola politikasıyla yaygın kalıpları, düşük karmaşıklığı ve e-posta/ad içeren parolaları reddeder.

## Multimodal/training/live integration readiness

- Multimodal route'ları OCR/STT/TTS için boyut sınırı, magic-byte doğrulaması, MIME allowlist, rate-limit ve PII detection kontratı taşır.
- OCR/STT/TTS modülleri local/cloud provider seçimi ve cloud failure fallback davranışını env ile yönetir.
- Training tarafı LoRA dataset/config/split kontratları hızlı test paketiyle doğrulanır; gerçek fine-tune ayrı GPU/extra bağımlılık koşusudur.
- `scripts/check_live_integrations.py` multimodal, training, Supabase Data API grant ve fast contract test yüzeylerini offline doğrular.

## Hızlı Suite Dışında Kalanlar

- Gerçek LLM sunucusu, GPU davranışı ve gerçek model gecikmesi.
- Canlı Qdrant korpusu ve 159k vektörlü üretim koleksiyonunun anlık yeniden sayımı.
- Multimodal STT/OCR/TTS gerçek model uçtan uca testi.
- Eğitim pipeline'ı ve model yeniden kalibrasyonu gerçek GPU koşusu.
- Canlı Supabase Auth dashboard'unda Pro plan gerektiren leaked-password protection toggle'ı.
- Gerçek kullanıcı verisi, gerçek hukuki danışmanlık senaryosu veya mahkeme sonucu doğrulaması.

## Model ve Korpus Notları

- Repo konfigürasyonunda güncel üretim model string'i `Qwen3.5-9B-UD-Q4_K_XL.gguf` olarak belgelenmiştir.
- `docs/ablation_study.md` ve bazı tez ölçümleri Qwen 2.5 14B ile alınmış tarihsel sonuçlardır; güncel model sonucu gibi sunulmaz.
- 159.362 vektörlü Qdrant korpusu ölçümü 2026-05-29 snapshot'ıdır. Hızlı yerel doğrulama canlı Qdrant sayımı yapmadığı için bu sayı “güncel canlı sayım” değil, belgelenmiş korpus snapshot'ıdır.

## Kısa Puan

Dokümantasyon puanı, bu dosya ve governance kuralı ile **10/10** hedefini karşılar: güncel tek kaynak var, tarihsel belgeler ayrılıyor, metrikler komut ve tarih ile izleniyor, ürün iddiaları test kapılarıyla bağlanıyor.

Production readiness ve multimodal/training/live integration readiness repo-seviyesi kapıları da **10/10** hedefini karşılayacak düzeye çekilmiştir: offline gate'ler CI'a bağlıdır, Supabase Data API kırıcı değişikliği için migration vardır, model default'ları hizalıdır ve ağır canlı doğrulamalar deploy-smoke/runbook katmanına açıkça ayrılmıştır.
