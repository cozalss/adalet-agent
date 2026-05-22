# Backend

FastAPI + LangGraph üzerinde Türkçe Hukuk AI Asistanı backend'i. Tüm Python kodu burada — API, ajanlar, RAG, multimodal.

## Modüller

```
backend/
├── main.py            FastAPI giriş noktası
├── pyproject.toml     Tüm Python bağımlılıkları
├── Dockerfile         Production image
├── agents/            7 ajan (Triaj, Mevzuat, Emsal, Dilekçe, Doğrulama, Tartışma, Tahmin)
├── retrieval/         RAG + yargi-mcp wrapper + Qdrant
├── multimodal/        OCR (Tesseract + Qwen2-VL), STT (Whisper), TTS (Coqui)
└── predictive/        ML tahmin modeli (opsiyonel)
```

## Çalıştır

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
```

`http://localhost:8000/docs` → Swagger UI.

## Test

```bash
uv run pytest --cov=. --cov-report=term-missing
```

%80 coverage hedef.

## Endpoint'ler

- `GET /health` → sağlık kontrolü
- `POST /chat` → ajanları çağırır, SSE ile cevap akar
- `POST /documents/upload` → belge OCR
- `POST /audio/transcribe` → ses STT

## Yapılacaklar

- [ ] FastAPI iskelet + `/health`
- [ ] LangGraph state graph
- [ ] Triaj + Mevzuat + Emsal ajanları
- [ ] Doğrulama ajanı (citation verify)
- [ ] Rate limiting
- [ ] Docker build
