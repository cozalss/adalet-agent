# Architecture Decision Records (ADR)

ADALET-AGENT Sprint-4 boyunca alınan mimari kararların kayıtları.

Format: [MADR](https://adr.github.io/madr/) lite.

## Index

| # | Karar | Durum | Tarih |
|---|---|---|---|
| [001](ADR-001-nli-contradiction-threshold.md) | NLI contradiction threshold 0.70 | Accepted | 2026-05-12 |
| [002](ADR-002-llm-mode-split.md) | LLM_MODE: mock / llamacpp_server split | Accepted | 2026-05-10 |
| [003](ADR-003-colbert-enable-default.md) | ColBERT default ON for production retrieval | Accepted | 2026-05-19 |
| [004](ADR-004-raptor-graphrag-opt-in.md) | RAPTOR + GraphRAG opt-in (env-gated) | Accepted | 2026-05-21 |
| [005](ADR-005-jwt-vs-api-key.md) | İki kanallı auth: JWT (user) + X-API-Key (B2B) | Accepted | 2026-05-23 |
| [006](ADR-006-pii-mask-vs-redact.md) | PII mask before persist, not after | Accepted | 2026-05-23 |
| [007](ADR-007-caddy-auto-tls.md) | Caddy 2 auto-TLS — Nginx + Certbot yerine | Accepted | 2026-05-24 |
| [008](ADR-008-benchmark-programmatic.md) | Programmatic benchmark gen (yargi-mcp + LLM) | Accepted | 2026-05-13 |
