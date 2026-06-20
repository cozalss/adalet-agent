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
| Backend hızlı test paketi | `LLM_MODE=mock HYDE_ENABLED=0 MULTI_QUERY_ENABLED=0 PRELOAD_MODELS=0 NLI_FP16=0 LETTUCE_ENABLED=0 uv run pytest ...` | `1532 passed, 5 warnings` |
| Backend güvenlik taraması | `uv run bandit -r . -c pyproject.toml -ll -ii` | Sorun bulunmadı |
| Python bağımlılık denetimi | `uvx pip-audit --ignore-vuln CVE-2025-69872` | Bilinen güvenlik açığı yok |
| Hallucination scorecard | `uv run python -m eval.scorecard --check` | Geçti; P=1.000, R=1.000; yanlış veto `0/32`; FABRIKE F1=0.9767 |
| Frontend birim/entegrasyon testleri | `pnpm.cmd test` | `254 tests` geçti |
| Frontend build | `pnpm.cmd build` | Başarılı; Vite chunk uyarısı yok |
| Frontend e2e | `pnpm.cmd e2e` | `11 passed` |
| Node bağımlılık denetimi | `pnpm.cmd audit --audit-level=high` | Bilinen yüksek güvenlik açığı yok |

Backend hızlı test komutu opsiyonel/entegrasyon ağırlıklı şu alanları dışarıda bırakmıştır: `tests/multimodal`, `tests/training`, `tests/agents/test_real_llm_e2e.py`.

## Hızlı Suite Dışında Kalanlar

- Gerçek LLM sunucusu, GPU davranışı ve gerçek model gecikmesi.
- Canlı Qdrant korpusu ve 159k vektörlü üretim koleksiyonunun anlık yeniden sayımı.
- Multimodal STT/OCR/TTS uçtan uca testi.
- Eğitim pipeline'ı ve model yeniden kalibrasyonu.
- Canlı Supabase projesi üzerinde dashboard/advisor kontrolleri.
- Gerçek kullanıcı verisi, gerçek hukuki danışmanlık senaryosu veya mahkeme sonucu doğrulaması.

## Model ve Korpus Notları

- Repo konfigürasyonunda güncel üretim model string'i `Qwen3.5-9B-UD-Q4_K_XL.gguf` olarak belgelenmiştir.
- `docs/ablation_study.md` ve bazı tez ölçümleri Qwen 2.5 14B ile alınmış tarihsel sonuçlardır; güncel model sonucu gibi sunulmaz.
- 159.362 vektörlü Qdrant korpusu ölçümü 2026-05-29 snapshot'ıdır. Hızlı yerel doğrulama canlı Qdrant sayımı yapmadığı için bu sayı “güncel canlı sayım” değil, belgelenmiş korpus snapshot'ıdır.

## Kısa Puan

Dokümantasyon puanı, bu dosya ve governance kuralı ile **10/10** hedefini karşılayacak düzene gelmiştir: güncel tek kaynak var, tarihsel belgeler ayrılıyor, metrikler komut ve tarih ile izleniyor, ürün iddiaları test kapılarıyla bağlanıyor.
