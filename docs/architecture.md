# ADALET-AGENT — System Architecture

> Sprint-4 Hafta 10 finalize. Doğrulamalı çoklu-ajan Türkçe hukuk RAG.

## Mimari Katmanlar (Mermaid)

```mermaid
flowchart TB
    subgraph Clients["Clients"]
        Web["Web (Next.js)"]
        Mobile["Mobile (Flutter)"]
        B2B["B2B Partner (HTTP)"]
    end

    Caddy["Caddy 2<br/>TLS + Security Headers"]

    subgraph Backend["FastAPI Backend"]
        Auth["Auth Middleware<br/>(JWT + API Key)"]
        Sanitize["Sanitize<br/>(PI filter)"]
        PII["PII Mask"]
        Limiter["Rate Limiter<br/>(Redis backend)"]
        Audit["Audit Log"]
    end

    subgraph Graph["LangGraph 7-Agent Pipeline"]
        Triaj["Triaj<br/>(domain classify)"]
        Mevzuat["Mevzuat<br/>(law retrieval)"]
        Emsal["Emsal<br/>(case retrieval + GraphRAG)"]
        Draft["Draft<br/>(LLM answer)"]
        Verify["Verify<br/>(4 layers)"]
        Debate["Debate<br/>(constitutional)"]
        Finalize["Finalize<br/>(confidence + disclaimer)"]
        SelfRAG["Self-RAG (opt-in)"]
        CRAG["CRAG (opt-in)"]
    end

    subgraph VerifyLayers["Verify Layers"]
        L1["L1: Rules"]
        L2["L2: Fuzzy"]
        L25["L2.5: LettuceDetect"]
        L3["L3: NLI veto"]
        L4["L4: RARR-lite (opt-in)"]
    end

    subgraph Retrieval["Hybrid Retrieval"]
        HyDE["HyDE"]
        MQ["Multi-Query (N=5)"]
        Embed["BGE-M3 dense+sparse+ColBERT"]
        Qdrant["Qdrant named vectors"]
        Rerank["Reranker bge-reranker-v2-m3"]
        RRF["RRF Fusion (k=60)"]
        RAPTOR["RAPTOR tree (opt-in)"]
        GraphRAG["GraphRAG NetworkX (opt-in)"]
    end

    subgraph External["External / Local"]
        LLM["llama-server<br/>(Qwen 2.5 14B Q4)"]
        Redis["Redis<br/>(session + limiter)"]
        Langfuse["Langfuse (observability)"]
    end

    Web --> Caddy
    Mobile --> Caddy
    B2B --> Caddy
    Caddy --> Auth
    Auth --> Sanitize --> PII --> Limiter --> Audit --> Graph
    Triaj --> Mevzuat
    Triaj --> Emsal
    Mevzuat --> Retrieval
    Emsal --> Retrieval
    Mevzuat --> Draft
    Emsal --> Draft
    Draft --> Verify --> Debate --> Finalize
    Verify -.-> CRAG
    Debate -.-> SelfRAG
    Verify --> VerifyLayers
    Retrieval --> Qdrant
    Draft --> LLM
    Verify --> LLM
    Debate --> LLM
    Backend -.-> Redis
    Backend -.-> Langfuse
```

## Veri Akışı — Tek Soru

```mermaid
sequenceDiagram
    actor U as Kullanıcı
    participant C as Caddy
    participant A as Auth
    participant S as Sanitize+PII
    participant G as LangGraph
    participant Q as Qdrant
    participant L as LLM
    participant Db as Redis

    U->>C: POST /ask (JWT)
    C->>A: authenticate
    A->>S: cleaned question
    S->>G: ainvoke(initial)
    G->>L: triaj prompt
    L-->>G: domain=isHukuku conf=0.95
    G->>Q: hybrid search (mevzuat)
    Q-->>G: 8 law refs
    G->>Q: hybrid search (emsal)
    Q-->>G: 8 case refs
    G->>L: draft prompt + refs
    L-->>G: draft + claims
    G->>G: verify (4 layers)
    G->>L: debate critique
    L-->>G: verdict=pass score=0.85
    G-->>S: final state
    S->>Db: persist turn (PII-masked)
    S-->>C: AskResponse
    C-->>U: 200 JSON
```

## Verify Verdict Aggregation

```mermaid
flowchart LR
    Claim --> L1{Rules}
    L1 -- pass --> L2{Fuzzy >= 0.55}
    L1 -- fail --> Unverified
    L2 -- yes --> Supported
    L2 -- no --> L25{Lettuce >= 0.45}
    L25 -- yes --> Supported
    L25 -- no --> L3{NLI entail >= 0.55}
    L3 -- yes --> Supported
    L3 -- contradiction >= 0.70 --> Veto
    L3 -- no --> Unverified
    Supported --> Aggregate
    Unverified --> Aggregate
    Veto --> Aggregate
    Aggregate -- contra ratio >= 0.5 --> Reject
    Aggregate -- supported ratio >= 0.20 --> Pass
    Aggregate -- retry < MAX --> Retry
    Aggregate -- else --> Reject
```

## Deploy Stack (Hetzner Staging)

```mermaid
flowchart LR
    DNS["staging.adalet.app<br/>(DNS A)"]
    Internet --> DNS
    DNS --> Hetzner
    subgraph Hetzner["Hetzner CCX23 / GPU"]
        Caddy2["Caddy 2<br/>(TLS, 80/443)"]
        Backend["FastAPI<br/>(8000, internal)"]
        Qdrant2["Qdrant<br/>(6333, internal)"]
        Redis2["Redis<br/>(6379, internal)"]
        LLM2["llama-server<br/>(8080, internal)"]
    end
    Caddy2 --> Backend
    Backend --> Qdrant2
    Backend --> Redis2
    Backend --> LLM2
    Backend -.-> S3["S3 / Hetzner<br/>Object Storage"]
    Backend -.-> LF["Langfuse Cloud"]
```

## Modüller (Backend)

| Dizin | Sorumluluk |
|---|---|
| `agents/` | LangGraph 12-node (triaj·mevzuat·emsal·draft·verify·debate·finalize + crag/self_rag/eligibility/tahmin/dilekçe) + state (merge_citations reducer) |
| `retrieval/` | Hybrid (BGE-M3 + RRF) + HyDE + Multi-Query + RAPTOR + GraphRAG + domain tier-sort |
| `verifier/` | NLI (mDeBERTa) + LettuceDetect + RARR |
| `db/` | PostgreSQL — engine + models + repositories (env-gated, dosya fallback) |
| `alembic/` | DB migration (async, DATABASE_URL'den) |
| `api/` | FastAPI routes + middleware (auth/sanitize/PII/audit/security-headers) |
| `api/routes/` | `/ask`, `/ask/stream`, `/multimodal/*`, `/auth/*`, `/feedback`, `/dilekce` |
| `core/` | Logging redact + PII-mask + observability (Langfuse) |
| `multimodal/` | OCR (Tesseract) + STT (Whisper) + TTS (Piper) |
| `predictive/` | Tahmin modeli (BERT-TR — eğitim bekliyor) |
| `eval/` | eval_run, freeze_baseline, edge_cases, ragas_full, judge |

## Önemli Sayılar (Sprint-4 Sonu)

| Metric | Sprint-3 sonu | Sprint-4 sonu (W10) |
|---|---|---|
| Test sayısı | 205 | 336 (+131) |
| Coverage | yok | 83.24% |
| mypy --strict | hayır | 0 hata (67 dosya) |
| ruff strict | hayır | 0 hata |
| Verify katman sayısı | 3 | 4 (RARR-lite) |
| Auth | yok | JWT + X-API-Key |
| TLS | yok | Caddy auto-TLS |
| PII mask | yok | TCKN, phone, email, IBAN, plate |
| Audit log | yok | structlog stream |
| CI/CD | manuel | GitHub Actions (4 job) |
| Container hardening | non-root | read-only fs, cap-drop ALL |

### Güncel (Sprint-6+ — 2026-05)

| Metric | Değer |
|---|---|
| Test sayısı | **662** |
| mypy --strict | 0 hata (**215 dosya**) · ruff ✅ · bandit ✅ |
| Corpus | **159k vektör** (8 domain; 62k→159k) |
| Retrieval | **domain@1 %81.2 · @5 %97.3 · MRR 0.88** (186 vaka, ölçüldü) |
| İlişkisel DB | **PostgreSQL** (feedback/api_key/audit, env-gated, Alembic) |
| Verify katman | 4 (fuzzy + LettuceDetect + NLI + debate) |
| Retry | re-retrieve (mevzuat+emsal, MAX_RETRY guard) + dedup reducer |

Ayrıntı: [theses/measured-results.md](theses/measured-results.md)

## Karar Bağlantıları (ADR)

- ADR-001: [NLI threshold 0.70](decisions/ADR-001-nli-contradiction-threshold.md)
- ADR-002: [LLM_MODE split](decisions/ADR-002-llm-mode-split.md)
- ADR-003: [ColBERT default on](decisions/ADR-003-colbert-enable-default.md)
- ADR-004: [RAPTOR + GraphRAG opt-in](decisions/ADR-004-raptor-graphrag-opt-in.md)
- ADR-005: [JWT + API key](decisions/ADR-005-jwt-vs-api-key.md)
- ADR-006: [PII mask hibrit](decisions/ADR-006-pii-mask-vs-redact.md)
- ADR-007: [Caddy auto-TLS](decisions/ADR-007-caddy-auto-tls.md)
- ADR-008: [Programmatic benchmark](decisions/ADR-008-benchmark-programmatic.md)
