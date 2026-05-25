# ADR-002 — LLM_MODE split: mock / llamacpp_server

**Durum:** Accepted
**Tarih:** 2026-05-10
**Sprint:** 4 / W1

## Bağlam
Sprint öncesi proje sadece "llamacpp_server" üzerinden geliştiriliyordu. Bu:
- Geliştirici makinesinde sürekli ~7GB GPU kullanıyor
- Test koşturmak için her seferinde llama-server kurulum şart
- CI/CD ortamında 2.5 dakika boyunca model yüklenirken pytest hang ediyor

Aynı zamanda **production'da gerçek LLM şart** — yoksa hiç değer üretmiyoruz.

## Karar
`LLM_MODE` env-flag ile iki implementasyon:

1. **`LLM_MODE=mock`** (default, CI ve dev için)
   - `MockLLM` — deterministic JSON router; her node için sabit fixture cevap
   - Hiç GPU/network kullanmaz; pytest 14s'de 336 test koşturur

2. **`LLM_MODE=llamacpp_server`** (production)
   - llama-server `127.0.0.1:8080` HTTP client
   - Qwen 2.5 14B Q4_K_M, RTX 4070 -ngl 20, ctx 8192

Test'lerde `LLM_MODE=mock` zorunlu (`tests/conftest.py`). Real-LLM
integration suite (`@pytest.mark.llm_integration`) sadece llama-server +
Qdrant ayakta iken çalışır (skip otherwise).

## Sonuç
- CI'da test süresi 2.5dk → 14s
- Geliştirici makinesinde GPU özgürce kapatılabiliyor
- Production değişmedi: llamacpp_server hâlâ default deploy
- W5'te real-LLM smoke (mock retrieval + real LLM) ile gerçek model
  davranışı doğrulanıyor (3/3 pass, avg 32.5s)

## Alternatifler
- **vLLM / TGI** — daha hızlı ama RTX 4070 12GB için fazla VRAM (Qwen 14B
  fp16 ~28GB).
- **OpenAI/Anthropic API** — CLAUDE.md production kuralı ihlali (yalnız lokal).

## İlgili
- [agents/llm.py:50](../../adalet-agent/backend/agents/llm.py#L50)
- [tests/conftest.py:11](../../adalet-agent/backend/tests/conftest.py#L11)
- [scripts/smoke_real_llm_mock_retrieval.py](../../adalet-agent/backend/scripts/smoke_real_llm_mock_retrieval.py)
