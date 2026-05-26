# Langfuse Setup — Trace + Observability

> Tarih: 2026-05-26
> Durum: Code v2 + v4 dual-import path destekler, runtime'da v4 import path
>        ayrı `langchain` paketi gerektiriyor.

## Durum

| Item | Durum |
|---|---|
| `langfuse>=2.50.0` paket | ✅ Kurulu (actual: v4.6.1) |
| `core/observability.py` | ✅ Yazıldı (v2 + v4 dual path) |
| `api/routes/ask.py:140-147` | ✅ Handler inject ediliyor |
| `.env` LANGFUSE_PUBLIC_KEY / SECRET_KEY | ⏸ Boş — yorum satırı olarak ekli |
| `langchain` package (v4 için gerek) | ❌ Kurulu değil |
| `/ask/stream` Langfuse | ❌ Callback config geçilmiyor (Sprint-6) |
| `AskResponse.trace_id` | ❌ Şemada yok (Sprint-6) |
| Test mock'u | ❌ tests/ altında yok (Sprint-6) |

## Langfuse v4 API Migration

**Önemli**: Langfuse v4'te (2025+) eski `langfuse.callback.CallbackHandler`
kaldırıldı. Yeni API:

```python
from langfuse.langchain import CallbackHandler   # v4+ (requires langchain pkg)
from langfuse import Langfuse, observe            # v4 standalone client + decorator
```

ADALET'te kullanacağımız 2 path var:

### Path A: Downgrade (kısa vade, Sprint-6'ya kadar)

```bash
# pyproject.toml içinde
langfuse>=2.50.0,<3.0
```

Sonra:
```powershell
uv sync
```

Eski v2 API tüm geri uyumlu, mevcut `observability.py` direkt çalışır.

### Path B: v4 Refactor (uzun vade, Sprint-6)

`observability.py`'yi `@observe` decorator pattern'ine taşı:

```python
from langfuse import observe

@observe(as_type="generation")
async def llm_call(prompt: str) -> str:
    ...

@observe()
async def ajan_node(state: dict) -> dict:
    ...
```

LangGraph node'larına decorator eklenmesi gerekir. Tahmini effort: 6-8 saat.

## Setup (Path A — Önerilen Şu An)

### 1. Langfuse Cloud Hesabı

https://cloud.langfuse.com → kayıt → yeni proje "adalet-agent".

Proje ayarlarından:
- Public key (pk-lf-...)
- Secret key (sk-lf-...)
- Host (default: https://cloud.langfuse.com)

### 2. .env Aktif Et

```bash
# adalet-agent/backend/.env
LANGFUSE_PUBLIC_KEY=pk-lf-xxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxx
LANGFUSE_HOST=https://cloud.langfuse.com
```

### 3. Langfuse v2.x'e Downgrade

```powershell
cd adalet-agent\backend
# pyproject.toml: langfuse>=2.50.0,<3.0  (geçici, Sprint-6'da v4'e geç)
uv sync
```

### 4. Smoke Test

```powershell
# llama-server arka planda çalışır (LLM_MODE=llamacpp_server)
cd adalet-agent\backend
uv run uvicorn main:app --reload --port 8000

# Ayrı terminal:
curl -X POST http://localhost:8000/ask `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $BETA_TOKEN" `
  -d '{"question":"Kıdem tazminatım nasıl hesaplanır?"}'
```

### 5. Dashboard

Langfuse Cloud → Traces → ilk trace 5-10s içinde gelir.

Beklenen trace yapısı:
```
[ask] (top-level)
  └─ triaj
  └─ mevzuat
       └─ embedding_call
       └─ qdrant_search
  └─ emsal
       └─ embedding_call
       └─ graph_traverse  (GRAPH_RAG_ENABLED=1 ise)
  └─ draft
       └─ llm_call (Qwen 14B-Q5)
  └─ verify
       └─ nli_batch
       └─ lettuce_call
  └─ debate
  └─ finalize
```

## Sprint-6 TODO

- [ ] `observability.py` v4 refactor (Path B)
- [ ] `/ask/stream` endpoint'inde callback inject
- [ ] `AskResponse.trace_id` field + frontend link
- [ ] `tests/core/test_observability.py` mock test
- [ ] Singleton Langfuse client lifespan init (flush kontrolü için)
- [ ] Cost report cronjob (`scripts/cost_report.py` mevcut, dashboard export)

## Maliyet

- Langfuse Cloud Hobby: 50K observation/ay ücretsiz
- Pro: $59/ay (1M observation)
- Beta phase (10 kullanıcı × ~5 soru/gün × 30 gün = 1500 trace × ~10 observation/trace = 15K) → Hobby tier yeterli

Self-host Langfuse: Hetzner staging'e Docker compose ile eklenebilir (Sprint-9).
