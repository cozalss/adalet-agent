# Typo Robustness Measurement

Date: 2026-06-17
Mode: `scripts.eval_run --mode node` production-path law retrieval

## Inputs

- Clean benchmark: `data/eval_benchmark/benchmark_v2.jsonl` (`n=186`)
- Typo benchmark: `data/eval_benchmark/typo_cases.jsonl` (`n=550`)
- Comparison output: `eval/runs/typo_retrieval_compare_node.json`
- Final typo-enabled output after conservative merge: `eval/runs/typo_cases_enabled_node_after_merge.json`

## Clean Benchmark

Typo tolerance did not change retrieval quality on clean questions.

| Metric | Typo off | Typo on |
| --- | ---: | ---: |
| domain@1 | 100.00% | 100.00% |
| kanun@5 | 97.31% | 97.31% |
| kanun@8 | 98.39% | 98.39% |
| madde_recall@5 | 57.23% | 57.23% |
| madde_recall@8 | 65.36% | 65.36% |
| p50 latency | 368.3 ms | 374.0 ms |
| p95 latency | 413.5 ms | 418.1 ms |

Additional guard check: `benchmark_v2` now produces `0/186` typo variants, so clean questions no longer open unnecessary typo branches.

## Typo Benchmark

| Metric | Typo off | Typo on |
| --- | ---: | ---: |
| domain@1 | 100.00% | 100.00% |
| kanun@5 | 96.55% | 96.73% |
| kanun@8 | 98.36% | 98.55% |
| keyword_recall | 60.92% | 62.09% |
| madde_recall@5 | 50.14% | 49.53% |
| madde_recall@8 | 59.82% | 60.53% |
| p50 latency | 361.6 ms | 404.9 ms |
| p95 latency | 423.1 ms | 571.3 ms |

By typo level with typo tolerance on:

| Typo level | n | domain@1 | kanun@5 | madde_recall@8 |
| --- | ---: | ---: | ---: | ---: |
| boundary | 186 | 100.00% | 96.77% | 59.14% |
| diacritic | 178 | 100.00% | 96.07% | 61.77% |
| single_edit | 186 | 100.00% | 97.31% | 60.74% |

## Decision

Sufficient for v1 production rollout behind `TYPO_TOLERANCE_ENABLED=1`.

Rationale:

- Clean benchmark quality is unchanged.
- Typo benchmark improves production-window `madde_recall@8` by +0.71pp.
- `kanun@5`, `kanun@8`, and keyword recall improve slightly.
- p95 latency increase on typo cases is about +148 ms, within the planned +200 ms budget.
- `madde_recall@5` drops by -0.61pp, but production passes `TOP_K_LAW=8` downstream; `@8` is the more relevant user-facing retrieval window.

Follow-up:

- Keep monitoring `madde_recall@5` in future changes.
- Consider a rerank-time fusion strategy if we want top-5 gains, not only top-8 recall.
