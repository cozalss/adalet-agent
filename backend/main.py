"""ADALET-AGENT API entry point.

POST /ask         → tek seferlik soru-cevap (LangGraph zinciri)
POST /ask/stream  → SSE; her node event yayar
GET  /health      → liveness + ana bileşenlerin durumu
"""

from __future__ import annotations

import contextlib
import hmac
import os
import sys
from contextlib import asynccontextmanager

# Windows cp1254 console + Türkçe karakter çakışması: structlog default
# PrintLoggerFactory print() ile cp1254'e yazar ve "İçtüzük" benzeri
# karakterlerde UnicodeEncodeError fırlatır → ASGI 500. stdout/stderr'i
# UTF-8'e zorla (Python 3.7+).
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Windows: pyarrow'u torch'tan ÖNCE yükle (Arrow↔torch native import-sıra
# çakışması → access violation; bkz. core/native_preload.py). `with` bloğu
# içinde olduğundan ruff/isort yeniden sıralamaz → kesinlikle EN ÖNDE çalışır,
# herhangi bir api.*/torch import'undan önce.
with contextlib.suppress(Exception):
    from core import native_preload as _native_preload  # noqa: F401

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.limiter import limiter
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.routes.ask import router as ask_router
from api.routes.auth import router as auth_router
from api.routes.conversations import router as conversations_router
from api.routes.dilekce import router as dilekce_router
from api.routes.feedback import router as feedback_router
from api.routes.multimodal import router as multimodal_router
from api.routes.preferences import router as preferences_router
from api.schemas import HealthResponse

log = structlog.get_logger()


def _configure_logging_safe() -> None:
    """structlog'u config et — redact + PII-mask processor zinciri devreye girsin.

    Sessiz suppress ETME (code-review): config başarısız olursa loglar MASKESİZ
    akar (KVKK riski) ve kimse fark etmez. Hata stderr'e yazılır (structlog henüz
    config edilmemiş olabilir → stdlib print).
    """
    try:
        from core.logging import configure_logging
        configure_logging()
    except Exception as exc:
        print(f"CRITICAL: configure_logging başarısız — loglar MASKESİZ: {exc}",
              file=sys.stderr, flush=True)


async def _init_db_if_enabled() -> None:
    """DATABASE_URL set ise tabloları idempotent oluştur (best-effort).

    Production'da Alembic tercih edilir; create_all ilk boot'u güvenceye alır.
    DB kapalıysa no-op (dosya fallback). Hata startup'ı bloke etmez.
    """
    try:
        from db import create_all, is_db_enabled
        if is_db_enabled():
            await create_all()
            log.info("db_ready")
    except Exception as exc:
        log.warning("db_init_failed", error=str(exc))


def _preload_heavy_models() -> None:
    """Heavy ML model'leri sync olarak main-thread'de warm up et (boot'ta).

    Request-time lazy load Windows'ta torch CPU init + asyncio çakışmasıyla
    segfault üretebiliyor; ayrıca singleton'lar boot'ta oluşturulunca ilk
    eşzamanlı istekler check-then-set yarışına girmez. Her blok best-effort:
    biri patlasa diğerleri yüklenir (graceful degrade).
    """
    # GERÇEK retrieval singleton'larını ısıt (request-yolu bunları kullanır). ÖNEMLİ:
    # eski preload düz `Embedder()`'ı ısıtıyordu ama retrieval `hybrid_search._get_embedder()`
    # (MursitEmbedder, sentence_transformers) + `_get_colbert_embedder()` (BAAI/bge-m3 CPU)
    # AYRI singleton'larını kullanıyor → ilk sorgu bu iki modeli COLD yüklüyordu (2026-06-18:
    # ilk sorgu ~22s'in ~12s'i bge-m3+Mursit cold-load, retrieval_done_ms'te görünür). Doğru
    # singleton'ları + ColBERT yolunu (return_colbert=True) boot'ta warm-up et.
    try:
        from retrieval.hybrid_search import _get_colbert_embedder, _get_embedder
        log.info("preload_embedder_start")
        emb = _get_embedder()  # request-yolundaki GERÇEK dense embedder (Mursit)
        try:
            emb.encode_query("warmup sorgusu")
        except Exception:
            emb.encode(["warmup sorgusu"])  # MursitEmbedder API farkına karşı defansif
        log.info("preload_embedder_done")
        # ColBERT rerank embedder (BAAI/bge-m3 CPU) — ilk sorgudaki ~10s cold-load'un kaynağı.
        # Yalnız bgem3 rerank provider'ı açıkken yükle (boşuna ~2GB model yüklemeyelim).
        if os.getenv("RERANK_PROVIDER", "").strip().lower() == "bgem3":
            log.info("preload_colbert_start")
            cb = _get_colbert_embedder()
            cb.encode_query("warmup sorgusu", return_colbert=True)  # ColBERT vec yolunu ısıt
            log.info("preload_colbert_done")
    except Exception as exc:
        log.warning("preload_embedder_failed", error=str(exc))

    try:
        from retrieval.reranker import get_reranker
        log.info("preload_reranker_start")
        rer = get_reranker()
        _ = rer._model  # force lazy load
        log.info("preload_reranker_done")
    except Exception as exc:
        log.warning("preload_reranker_failed", error=str(exc))

    # NLI cross-encoder: verify katmanının (CLATTER/CITE-grounding) ÇEKİRDEĞİ ve ÖLÇÜLEN
    # en pahalı cold-load (2026-06-18: ilk sorgu ~45s'in ~10.9s'i NLI lazy-load; sıcak ~1.5s).
    # Boot'ta warm-up (model yükle + 1 forward) → ilk KULLANICI sorgusu bu cezayı yemez
    # (boot görünmez, ilk sorgu görünür → demoda en kritik latency kazancı). Best-effort.
    # NOT: lettuce default token-coverage (use_raw_model=False) → ağır model yok, preload gereksiz.
    try:
        from agents.verifier_layers import get_verifier
        log.info("preload_nli_start")
        nli = get_verifier()
        _ = nli.verify("warmup hipotezi", "warmup öncül kanıt metni")  # load + ilk forward
        log.info("preload_nli_done")
    except Exception as exc:
        log.warning("preload_nli_failed", error=str(exc))

    # LLM (in-process Qwen GGUF) boot-warm — OPT-IN (PRELOAD_LLM=1). Lazy load ilk KULLANICI
    # sorgusuna ~13s GPU-yükleme cezası bindiriyor (2026-06-18: ilk sorgu ~28s'in baskını).
    # Boot'ta yüklenirse ilk sorgu ≈ sıcak sorgu (~11s) — demoda en görünür kazanç. Default
    # KAPALI: prod/llama-server/mock konfigürasyonlarını etkilemesin (yalnız in-process client'ta
    # _load var). VRAM zirvesi değişmez (zaten çalışırken yüklü), yalnız zamanlaması öne alınır.
    if os.environ.get("PRELOAD_LLM", "0").lower() in {"1", "true", "yes"}:
        try:
            from agents.llm import get_llm
            client = get_llm()
            if getattr(client, "_model", "n/a") is None and hasattr(client, "_load"):
                log.info("preload_llm_start")
                client._model = client._load()  # mmap (hızlı); ağırlıklar ilk forward'da GPU'ya
                # llama.cpp mmap → _load yalnız haritalıyor; GERÇEK GPU-upload ilk inference'ta.
                # 1-token warmup ile o ~13s yükleme cezasını boot'a taşı (ilk soru ≈ sıcak).
                client._model.create_chat_completion(
                    messages=[{"role": "user", "content": "merhaba"}], max_tokens=1,
                )
                log.info("preload_llm_done")
        except Exception as exc:
            log.warning("preload_llm_failed", error=str(exc))

    # Qdrant client singleton'ını boot'ta oluştur: ilk eşzamanlı istekler
    # check-then-set yarışına girmesin (tek client, orphan bağlantı yok).
    try:
        from retrieval.vector_store import get_shared_client
        get_shared_client()
        log.info("preload_qdrant_client_done")
    except Exception as exc:
        log.warning("preload_qdrant_client_failed", error=str(exc))

    # Sprint-4 W3.2: RAPTOR pickle yüklemesi. RAPTOR_ENABLED=0 ise no-op,
    # pickle yoksa boş index → query() [] döner. Build offline:
    # `uv run python -m scripts.build_raptor`.
    try:
        from retrieval.raptor_runtime import get_raptor_index
        log.info("preload_raptor_start")
        idx = get_raptor_index()
        if idx is not None:
            log.info("preload_raptor_done", built=idx.built, n_nodes=len(idx.all_nodes()))
        else:
            log.info("preload_raptor_disabled")
    except Exception as exc:
        log.warning("preload_raptor_failed", error=str(exc))


async def _refresh_api_key_cache_safe() -> None:
    """API key cache'i repo'dan (DB/dosya) doldur — boot'ta bir kez.

    Auth hot-path'i sync cache kullanır; DB sorgusu yalnız burada yapılır.
    Sessizce yutMA: DB modunda refresh fail olursa cache boş kalır → tüm
    X-API-Key istekleri 401 alır. Misconfig'in fark edilmesi için error logla.
    """
    try:
        from api.middleware.auth import refresh_api_key_cache
        await refresh_api_key_cache()
        log.info("api_key_cache_refreshed")
    except Exception as exc:
        log.error("api_key_cache_refresh_failed", error=str(exc))


def _log_auth_visibility() -> None:
    """Boot'ta auth durumunu görünür logla + PRODUCTION FAIL-FAST (güvenlik C1).

    ENV=production iken korumasız (AUTH_ENABLED=0) veya secret'sız konfig startup'ı
    ÇÖKERTİR — sessiz misconfig ile korumasız production'a çıkmayı imkânsız kılar.
    Lokal dev (ENV!=production) yalnız uyarı loglar.
    """
    from api.middleware import auth as _auth
    is_prod = os.getenv("ENV", "").lower() in {"production", "prod"}

    # SIFIR-HALÜSİNASYON ablation/ölçüm kaldıraçları production'da YASAK (ECC sweep, fail-fast):
    # VERIFY_ENABLED=0 doğrulama katmanını tümüyle bypass eder; FORCE_RETRY_ONCE=1 her isteği
    # retry'a zorlar. Yalnız izole test/ölçüm harness'ında kullanılır; production'a sızması engellenir.
    if is_prod:
        if os.getenv("VERIFY_ENABLED", "1").lower() not in {"1", "true", "yes"}:
            raise RuntimeError(
                "GÜVENLİK: ENV=production AMA VERIFY_ENABLED!=1 — doğrulama bypass edilir "
                "(sıfır-halüsinasyon garantisi kalkar). Ablation yalnız izole harness'ta."
            )
        if os.getenv("FORCE_RETRY_ONCE", "0").lower() in {"1", "true", "yes"}:
            raise RuntimeError(
                "GÜVENLİK: ENV=production AMA FORCE_RETRY_ONCE=1 — ölçüm hook'u her isteği "
                "gereksiz retry'a zorlar. Production'da kapalı olmalı."
            )

    if not _auth.AUTH_ENABLED:
        if is_prod:
            raise RuntimeError(
                "GÜVENLİK (C1): ENV=production AMA AUTH_ENABLED!=1 — tüm endpoint'ler "
                "korumasız. Production'da AUTH_ENABLED=1 zorunlu (fail-fast)."
            )
        log.warning(
            "auth_disabled",
            hint="AUTH_ENABLED=0 — endpoint'ler anonim erişime açık (lokal dev).",
        )
        return

    # Auth açık — sağlayıcıya göre doğrulama anahtarı zorunlu, yoksa tüm token'lar 500.
    if _auth.AUTH_PROVIDER == "supabase" and not (_auth.SUPABASE_URL or _auth.SUPABASE_JWT_SECRET):
        msg = ("AUTH_PROVIDER=supabase AMA SUPABASE_URL ve SUPABASE_JWT_SECRET ikisi de boş — "
               "frontend token'ları doğrulanamaz (500). Modern ES256: SUPABASE_URL="
               "https://<ref>.supabase.co ayarla (secret GEREKMEZ).")
        if is_prod:
            raise RuntimeError("GÜVENLİK (C2): " + msg)
        log.critical("auth_supabase_without_key", hint=msg)
    elif _auth.AUTH_PROVIDER != "supabase" and not _auth.JWT_SECRET:
        msg = "AUTH_ENABLED=1 ama JWT_SECRET boş — JWT decode 500 döner."
        if is_prod:
            raise RuntimeError("GÜVENLİK: " + msg)
        log.critical("auth_enabled_without_secret", hint=msg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: log mode + preload BGE-M3 & Reranker + request-path singleton warm-up.

    Neden preload? Lazy load uvicorn + asyncio + Windows + torch CPU init
    kombinasyonu request anında SIGSEGV (exit 139) yaratıyor. Modelleri
    main thread'in startup'ında, request henüz hiç gelmeden yüklemek
    bu çakışmayı önler. Preload PRELOAD_MODELS=0 ile devre dışı (test ortamı).

    Ayrıca request-path singleton'ları (graph/llm/store) warm-up edilir: ilk
    istek soğuk başlamaz ve config hataları boot'ta yüzeye çıkar. Bu warm-up
    torch yüklemez, PRELOAD_MODELS'ten bağımsız çalışır.
    """
    # Gizlilik kritik: structlog'u EN ÖNCE config et — redact + PII-mask zinciri.
    _configure_logging_safe()

    # Auth görünürlüğü: docker-compose AUTH_ENABLED=1 set eder; docker dışında
    # (uvicorn --reload) default 0 → endpoint'ler korumasız. Boot'ta GÖRÜNÜR
    # yap ki production yanlış-konfigürasyon sessiz kalmasın (security C1).
    _log_auth_visibility()

    log.info(
        "adalet_starting",
        llm_mode=os.environ.get("LLM_MODE", "mock"),
        hyde=os.environ.get("HYDE_ENABLED", "0"),
        embedding=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
    )

    if os.environ.get("PRELOAD_MODELS", "1").lower() in {"1", "true", "yes"}:
        _preload_heavy_models()

    # Request-path singleton'larını startup'ta eager warm-up et: compiled graph,
    # LLM client, session store. İki kazanç:
    #   1. İlk istek "soğuk" başlamaz — graph compile / client init / store bağlama
    #      maliyeti boot'a kaydırılır, kullanıcı latency'sine değil.
    #   2. Config hataları (örn. LLM_MODE=llamacpp ama LLM_MODEL_PATH yok) boot'ta
    #      yüzeye çıkar; ilk kullanıcı isteğinde 500 olarak patlamaz.
    # PRELOAD_MODELS'ten bağımsız: bu factory'ler torch yüklemez (mock/server modda
    # hafif), Windows segfault riski taşımaz. Her biri izole try/except — bir warm-up
    # başarısız olursa lazy yol fallback olarak kalır, startup bloke olmaz.
    try:
        from agents.llm import get_llm
        get_llm()
        log.info("warmup_llm_done")
    except Exception as exc:
        log.warning("warmup_llm_failed", error=str(exc))

    try:
        from api.session_store import get_store
        get_store()
        log.info("warmup_store_done")
    except Exception as exc:
        log.warning("warmup_store_failed", error=str(exc))

    # Embedding/koleksiyon boyut tutarlılığı — fail-fast (sessiz 768×1024 crash'i
    # boot'ta görünür yap). Koleksiyon yoksa veya model bilinmiyorsa sessizce geçer.
    try:
        from retrieval.vector_store import assert_collection_dim
        await assert_collection_dim()
    except RuntimeError as exc:
        log.error("collection_dim_mismatch", error=str(exc))
        raise  # production'da boot'u durdur — yanlış config ile çalışmaktansa patla
    except Exception as exc:
        log.warning("collection_dim_check_error", error=str(exc))

    # İlişkisel DB (DATABASE_URL set ise) — idempotent tablo oluştur.
    await _init_db_if_enabled()

    # API key cache (boot'ta repo'dan doldur — helper'da hata loglanır).
    await _refresh_api_key_cache_safe()

    try:
        from api.routes.ask import _get_graph
        _get_graph()
        log.info("warmup_graph_done")
    except Exception as exc:
        log.warning("warmup_graph_failed", error=str(exc))

    # Sprint-5 W16: APScheduler — Resmi Gazete + Yargıtay delta cron.
    # SCHEDULER_ENABLED=0 ile devre dışı (test/CI default).
    scheduler = None
    try:
        from core.scheduler import make_scheduler
        scheduler = make_scheduler()
        if scheduler is not None:
            scheduler.start()
            log.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])
    except Exception as exc:
        log.warning("scheduler_start_failed", error=str(exc))

    yield

    # Shutdown
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
            log.info("scheduler_shutdown")
        except Exception as exc:
            log.warning("scheduler_shutdown_failed", error=str(exc))
    # W8.1 v4: pending Langfuse traces flush
    try:
        from core.observability import flush_langfuse
        flush_langfuse()
    except Exception as exc:
        log.warning("langfuse_flush_failed_on_shutdown", error=str(exc))
    # Paylaşılan Qdrant client'ı kapat (request path singleton'ı).
    try:
        from retrieval.vector_store import aclose_shared_client
        await aclose_shared_client()
        log.info("qdrant_shared_client_closed")
    except Exception as exc:
        log.warning("qdrant_close_failed_on_shutdown", error=str(exc))
    # DB engine dispose (best-effort)
    with contextlib.suppress(Exception):
        from db import aclose_engine
        await aclose_engine()
    log.info("adalet_shutting_down")


app = FastAPI(
    title="ADALET-AGENT API",
    version="0.2.0",
    description="Türkçe Hukuk AI Asistanı — çoklu-ajan, doğrulamalı RAG",
    lifespan=lifespan,
)

# Rate limiter — slowapi tek-process in-memory backend default
# (RATE_LIMIT_STORAGE_URI env ile Redis'e bağlanabilir). 429 handler shim
# IP başına RATE_LIMIT_ASK (default 10/minute) /ask çağrısını sınırlar.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — Next.js (3000) ve Flutter web debug (8080) default; production
# için ALLOWED_ORIGINS env ile genişlet ("," ile ayrılmış URL listesi).
# Örnek: ALLOWED_ORIGINS=https://adalet.app,https://*.adalet-staging.vercel.app
_DEFAULT_ORIGINS = (
    "http://localhost:3000,"
    "http://localhost:8080,"
    "http://127.0.0.1:3000,"
    "http://127.0.0.1:8080"
)


def _parse_origins(raw: str) -> list[str]:
    """Virgülle ayrılmış string → temizlenmiş URL listesi."""
    return [o.strip() for o in raw.split(",") if o.strip()]


_origins_env = os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS)
_allow_origins = _parse_origins(_origins_env)

# Wildcard ("*") + allow_credentials=True kombinasyonu spec-dışı; tarayıcı
# reddeder. Wildcard varsa credentials'ı kapat.
_allow_credentials = "*" not in _allow_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Requested-With"],
)
log.info("cors_configured", origins=_allow_origins, credentials=_allow_credentials)

# Güvenlik başlıkları — her response'a HSTS/nosniff/DENY/Referrer-Policy ekle.
# CORS'tan SONRA eklenir → response'ta CORS başlıklarıyla birlikte döner.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(ask_router)
app.include_router(multimodal_router)
app.include_router(auth_router)
app.include_router(feedback_router)
app.include_router(dilekce_router)
app.include_router(preferences_router)
app.include_router(conversations_router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Sprint-4 W8.2: depth health — Qdrant + Redis + LLM ping.

    Status:
      - "ok"        — tüm bağımlılıklar erişilebilir
      - "degraded"  — opsiyonel bileşen down (LLM mock'a düştü vs.)
      - "unhealthy" — kritik bileşen erişilemez (Qdrant) — 503 dön
    """
    components: dict[str, str] = {
        "llm_mode": os.environ.get("LLM_MODE", "mock"),
        "hyde_enabled": os.environ.get("HYDE_ENABLED", "0"),
    }
    status_levels: list[str] = []

    # Sprint-4 W8.2: dev mode (LLM_MODE=mock) → external bağımlılıklar opsiyonel,
    # health 200 dönsün; production mode (llamacpp_server) → Qdrant zorunlu.
    is_dev = os.environ.get("LLM_MODE", "mock") == "mock"

    # Qdrant
    try:
        import httpx as _httpx
        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        async with _httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{qdrant_url}/healthz")
            components["qdrant"] = "ok" if r.status_code == 200 else f"http{r.status_code}"
            if r.status_code != 200 and not is_dev:
                status_levels.append("unhealthy")
            elif r.status_code != 200:
                status_levels.append("degraded")
    except Exception as exc:
        components["qdrant"] = f"down: {type(exc).__name__}"
        status_levels.append("degraded" if is_dev else "unhealthy")

    # Redis (session_store get_store internals)
    try:
        from api.session_store import get_store
        store = get_store()
        ok = await store.health()
        components["redis"] = "ok" if ok else "fail"
        if not ok:
            status_levels.append("degraded")
    except Exception as exc:
        components["redis"] = f"down: {type(exc).__name__}"
        status_levels.append("degraded")

    # LLM
    if os.environ.get("LLM_MODE") == "llamacpp_server":
        try:
            import httpx as _httpx
            url = os.environ.get("LLM_SERVER_URL", "http://127.0.0.1:8080")
            async with _httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{url}/health")
                components["llm"] = "ok" if r.status_code == 200 else f"http{r.status_code}"
                if r.status_code != 200:
                    status_levels.append("degraded")
        except Exception as exc:
            components["llm"] = f"down: {type(exc).__name__}"
            status_levels.append("degraded")
    else:
        components["llm"] = "mock"

    if "unhealthy" in status_levels:
        from fastapi.responses import JSONResponse
        body = HealthResponse(status="down", components=components).model_dump()
        return JSONResponse(status_code=503, content=body)  # type: ignore[return-value]
    status_value = "degraded" if status_levels else "ok"
    return HealthResponse(status=status_value, components=components)


def _require_metrics_token(request: Request) -> None:
    """Opsiyonel METRICS_TOKEN guard (defense-in-depth, denetim 2026-06-04).

    METRICS_TOKEN env AYARLIYSA: /metrics* yalnız `Authorization: Bearer <token>` veya
    `X-Metrics-Token` başlığı ile erişilir (timing-bilgisi sızıntısı + reverse-proxy yanlış-
    yapılandırması koruması). AYARLI DEĞİLSE davranış DEĞİŞMEZ → mevcut ağ-izolasyonuna
    güvenilir (private deploy / özel-ağ Prometheus scrape bozulmaz).
    """
    token = os.getenv("METRICS_TOKEN", "").strip()
    if not token:
        return
    auth = request.headers.get("authorization", "")
    supplied = (
        auth[7:].strip() if auth[:7].lower() == "bearer "
        else request.headers.get("x-metrics-token", "")
    )
    if not (supplied and hmac.compare_digest(supplied, token)):
        raise HTTPException(status_code=401, detail="metrics token gerekli")


@app.get("/metrics/latency")
@limiter.limit("60/minute")
async def metrics_latency(request: Request) -> dict:
    """SSE stream stage latans yüzdelikleri — P50/P95/P99 görünürlüğü.

    "P95/P99 trendi görünmezse kör uçarız." In-process rolling pencere (son 500
    istek). Dış scraper (Prometheus) yerine doğrudan okunabilir JSON.

    Çıktı: her stage için {n, p50, p95, p99, max, avg} (ms).
      stream.first_event_ms    — ilk node (graph başladı)
      stream.retrieval_done_ms — mevzuat+emsal geldi
      stream.first_token_ms    — draft başladı (token-stream yok → proxy)
      stream.final_ms          — uçtan uca toplam

    KISIT: tek-process pencere; multi-worker dağıtımda her worker ayrı snapshot.
    Kalıcı trend için JSON log'ları (stream_timings) bir aggregator'a aktarın.
    """
    _require_metrics_token(request)
    from core.metrics import snapshot_all
    return {"window": 500, "stages": snapshot_all()}


@app.get("/metrics")
@limiter.limit("60/minute")
async def metrics_prometheus(request: Request):
    """Prometheus exposition format — Grafana scrape path (self-hosted, KVKK-safe).

    Pipeline stage latans yüzdelikleri (P50/P95/P99) gauge olarak. Prometheus
    bu endpoint'i scrape eder, Grafana trend çizer. Veri kutudan ÇIKMAZ
    (Langfuse cloud yerine — CLAUDE.md §3 KVKK kuralı). PII/soru içeriği YOK,
    yalnız zamanlama sayıları.

    PRODUCTION: internal-only olmalı — Caddy/reverse-proxy public rotaya AÇMAMALI;
    Prometheus özel ağ (adalet-net) içinden scrape etsin.

    İnsan-okuması için JSON sürüm: GET /metrics/latency.
    """
    _require_metrics_token(request)
    from fastapi.responses import PlainTextResponse

    from core.metrics import render_prometheus
    return PlainTextResponse(render_prometheus(),
                             media_type="text/plain; version=0.0.4; charset=utf-8")
