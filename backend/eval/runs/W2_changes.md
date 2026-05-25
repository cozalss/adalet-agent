# Sprint-4 Hafta 2 — Benchmark Expansion + Eval Metrics Changelog

Plan referansı: `C:\Users\cemmo\.claude\plans\kategori-detay-alan-puan-majestic-valiant.md`
Önceki: `eval/runs/W1_changes.md`

## Hedef
50 → 200 vaka balanced benchmark; p95/p99/context_precision metrics; edge_cases
güçlendirme; Ragas answer_relevancy fix; LLM-Judge tam örneklem.

## Değişiklikler

### W2.1 — Programmatic benchmark generator
- Yeni `data/eval_benchmark/topics_v2.json` — 8 domain × topic phrase listesi
  (kanun_kodu mapping ile), 60+ unique topic
- Yeni `scripts/generate_benchmark.py`:
  - `--offline` (default) deterministic gen, network gerek değil
  - `--online` opsiyonel yargi-mcp ile keyword enrichment
  - `--variants N` topic başına soru varyantı (default 2)
  - Pattern-based question synthesis (LLM-siz)
- Çıktı: `data/eval_benchmark/benchmark_v2_generated.jsonl` (136 vaka, variants=2)

### W2.2 — Balanced merge → benchmark_v2.jsonl (186 vaka)
- Yeni `scripts/merge_benchmark_v2.py`:
  - Legacy 50 + programmatic 136 → dedup → re-seq ID (`V_{domain}_{NNN}`)
  - Source etiketleme (legacy / programmatic_v2)
  - Dağılım raporu
- **Final dağılım:**
  ```
  isHukuku  43    icra      26
  tuketici  42    trafik    11
  kira      33    vergi     11
  tapu      10    idari     10
  ```
- Toplam 186 vaka (plan hedefi 200'e %93); İK/Tüketici/Kira oransal olarak güçlü.

### W2.3 — freeze_baseline yeni metrics + benchmark seçimi
- `eval/freeze_baseline.py`:
  - Yeni `_percentile()` helper — p50/p95/p99 tutarlı hesaplama
  - `_summarize()` → context_precision@5 + p50/p95/p99 latency
  - `_parse_args()` → `--benchmark v1|v2` flag (default v1)
  - `payload`'a `benchmark_version`, `n_cases` ek
  - Output suffix: `v2_w2_<sha>.json` (v2 benchmark için)
- `scripts/eval_run.py`:
  - `_load_benchmark(version="v1"|"v2")` parametrize
  - `_eval_one()` → `context_precision@5` field eklendi
    (top-5 sonuçların kaçı expected_domain'e uyumlu)

### W2.4 — Edge cases güçlendirildi
- `eval/edge_cases.py`:
  - `_TCKN_RE` lookaround ile güçlendirildi (`(?<!\d)...(?!\d)`)
    — uzun rakam dizilerinde false-positive engellenir
  - `_PHONE_RE` regex tightened (trailing digit guard)
  - **YENİ:** `_EMAIL_RE` (RFC-lite)
  - **YENİ:** `_IBAN_RE` (TR + 24 hane)
  - **YENİ:** `_PLATE_RE` (TR plaka, 01–81 il)
  - `_has_pii()` toplu tarayıcı — herhangi bir pattern hit → PII redact
  - `classify_outcome` artık `_has_pii()` kullanıyor
- **8 yeni adversarial vaka:** PI-5 (system prompt sızdırma), PI-6 (base64
  smuggling), PII-3 (email+IBAN), PII-4 (plaka+telefon), SCOPE-4 (kasten
  yaralama), AGY-3 (UYAP işlem), REL-2 (disclaimer baskısı), OUT-2 (token DoS)
- **Tests:** 38/38 yeşil (30 eski + 8 yeni PII regex testleri)

### W2.5 — Ragas answer_relevancy lazy-load + format bug
- **Bonus bug yakalandı:** `_RELEVANCY_SYSTEM`'deki `{"questions": [...]}`
  JSON örneğinin `{` / `}` parantezleri `str.format(n=...)` çağrısında
  placeholder olarak yorumlanıyor → `KeyError: '"questions"'`. Eski sürüm
  answer_relevancy HER VAKADA silent fail ediyordu. Çift parantez `{{`/`}}`
  ile escape edildi → ŞİMDİ gerçekten çalışıyor.
- `eval/ragas_full.py`:
  - `RAGAS_RELEVANCY_FALLBACK_SCORE` env-toggle (default 0.5)
  - `_cosine_similarity_batch` → `(sims, embed_ok)` tuple döner
    (embed fail vs math edge ayırması)
  - `answer_relevancy` NaN yerine fallback skor döner
  - `except Exception` → `except (OSError, RuntimeError)` daraltıldı
- `tests/conftest.py` → autouse fixture ile `_cosine_similarity_batch` mock'lanıyor
  (Windows + asyncio + torch.cpu BGE-M3 yüklemesi segfault yapıyor)
- **Tests:** 16/16 yeşil (14 eski + 2 yeni fallback davranışı)

### W2.6 — LLM-Judge tam örneklem + determinism
- `eval/judge.py`:
  - `JUDGE_SAMPLE_RATE` default 0.20 → **1.0** (tam örneklem)
  - Env override hâlâ mümkün: `JUDGE_SAMPLE_RATE=0.20`
- Yeni test `test_judge_deterministic_repeat`: 3 ardışık çağrı identical
  output verir (temperature=0.0 + JSON-mode + tam kapsam)
- Yeni test `test_judge_sample_rate_default_is_full`: env override yoksa
  default 1.0
- **Tests:** 15/15 yeşil (13 eski + 2 yeni W2.6)

## Test Skoru
- **W1 sonu:** 213 / 213 yeşil
- **W2 sonu:** **225 / 225 yeşil** (+12 yeni)
- Regression: 0

## Kullanıcı Tarafından Çalıştırılması Gerekenler

### Benchmark üretimi (yerel, network gerek YOK)
```bash
cd backend
PRELOAD_MODELS=0 uv run python -m scripts.generate_benchmark --variants 2
PRELOAD_MODELS=0 uv run python -m scripts.merge_benchmark_v2
# Çıktı: data/eval_benchmark/benchmark_v2.jsonl (186 vaka)
```

### Online enrichment (opsiyonel, yargi-mcp gerek)
```bash
YARGI_MCP_URL=https://yargimcp.surucu.dev/mcp \
  uv run python -m scripts.generate_benchmark --variants 2 --online
# Karar referansı + zenginleştirilmiş keyword
```

### v2 benchmark ile freeze_baseline (RTX 4070 + llama-server)
```bash
HYDE_ENABLED=1 MULTI_QUERY_ENABLED=1 COLBERT_QUERY_ENABLED=1 \
  MEVZUAT_DOMAIN_FILTER=1 JUDGE_SAMPLE_RATE=1.0 \
  LLM_MODE=llamacpp_server HF_HUB_OFFLINE=1 PYTHONUTF8=1 \
  uv run python -m eval.freeze_baseline \
    --modes hybrid,rerank,hyde,multi_query \
    --benchmark v2
# Çıktı: eval/runs/v2_w2_<sha>.json (186 vaka × 4 mode)
```

## Bilinen Risk / Sınırlamalar

- **Programmatic vakalar daha kaba** — manuel-etiketli legacy 50 vakaya
  göre keyword/madde_no daha basit (template-based). Online enrichment ile
  kalite artırılabilir; akademik makale için bu sınır açıkça yazılmalı.
- **186 / 200 hedef:** %93 ulaşım. Hedef 200 için ya topics_v2.json'da
  daha çok phrase, ya `--variants 3` (= 204 vaka, biraz overlap riski).
- **answer_relevancy artık gerçek BGE-M3 yüklüyor** — test'lerde mock şart;
  production'da PRELOAD_MODELS=1 ile lifespan'da preload.
- **context_precision@5 sadece domain-match** (Ragas LLM-as-judge değil).
  Tam Ragas LLM context_precision `eval/ragas_full.py:269` zaten mevcut;
  freeze_baseline'a entegre edilmedi (latency düşürmek için).

## W3 İçin Hazır Zemin
- benchmark_v2 ile RAPTOR + GraphRAG ölçümleri yapılabilir
- LLM-Judge tam örneklem aktif → her yeni feature'ın judge skoru bilinir
- 24 edge case ile production prompt-injection guard test edilebilir
- Format bug fix'ten sonra answer_relevancy gerçek sinyal verir
