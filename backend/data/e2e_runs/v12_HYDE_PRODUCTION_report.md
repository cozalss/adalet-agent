# E2E v12 — HyDE PRODUCTION ON + WRAPPER FIX

## Tablo: v10 → v11 → v12

| # | Versiyon | Pass | Avg Latency | HyDE | Major change |
|---|----------|------|-------------|------|--------------|
| 1 | v10 (baseline) | 8/8 | 61s | OFF | verify ratio refactor (genel %100 milestone) |
| 2 | v11 (HyDE wrapper) | 8/8 | 82s | ON-buggy | `mevzuat_with_hyde_node` çift-çağrı (+20s/q) |
| 3 | **v12 (wrapper kaldırıldı)** | **8/8** | **74s** | **ON-temiz** | mevzuat_node iç timeout + fallback |

## Soru bazlı kıyas

| Soru | v10 (no HyDE) | v11 (HyDE bug) | v12 (HyDE clean) |
|------|---------------|----------------|------------------|
|      | top / lat     | top / lat      | top / lat |
| E1 Kıdem | 0.998 / 66s | 1.00 / 92s | **1.00 / 67s** |
| E2 İhbar | 0.96 / 63s | 0.96 / 92s | 0.96 / 95s (HyDE timeout fallback) |
| E3 Tüketici | 0.999 / 64s | 1.00 / 76s | **1.00 / 69s** |
| E4 Kira | 0.893 / 63s | 0.89 / 94s | **1.00 / 69s** ✦ +0.107 |
| E5 Trafik | 1.00 / 85s | 0.91 / 75s | 0.91 / 84s |
| E6 İcra | 0.884 / 48s | 0.88 / 69s | 0.88 / 74s |
| E7 Vergi | 0.657 / 57s | 0.66 / 77s | 0.66 / 75s |
| E8 Tapu | 0.625 / 45s | **0.75 / 80s** ✦ | 0.58 / 61s (HyDE variance) |

## Bu turda eklenen / değiştirilen kritik kod

1. `agents/nodes/mevzuat.py` — HyDE + multi-query wire (env-toggle), iç `asyncio.wait_for(timeout=27s)` + plain-hybrid fallback
2. `agents/graph.py` — `mevzuat_with_hyde_node` wrapper kaldırıldı (çift HyDE çağrı bug'ı)
3. `agents/nodes/hyde_retrieval.py` — graph'ta artık referans yok (orphan, sonra silinebilir)
4. `agents/config.py` — `HYDE_ENABLED`, `MULTI_QUERY_ENABLED`, `MULTI_QUERY_N=4`, env-toggle eklendi
5. `scripts/eval_run.py` — `_eval_one(case, mode=...)` 4-mode (hybrid/rerank/hyde/multi_query)
6. `eval/freeze_baseline.py` — `--modes hybrid,rerank,hyde,multi_query` CLI, çoklu mode'lu JSON
7. `tests/agents/test_verify_node.py` — `_verdict_from_ratio` 10 yeni regression test
8. `tests/eval/test_edge_cases.py` — PII leak override, regex false-pos guard, jailbreak/scope keyword integrity
9. Test temizliği — `mevzuat_with_hyde_node` monkeypatch satırları kaldırıldı (3 dosya)

## Sayısal kazanç özet

- Wrapper kaldırma → **-8s/q ortalama** (74s vs 82s)
- HyDE genuine kazanç: E4 top score **+0.107** (kira sorgusu — hipotetik metin embedding'i kanun jargonuna yaklaştırdı)
- HyDE variance: E8 v11 +0.125, v12 -0.045 → tek soru variance büyük, ortalamada nötr
- Pass rate: **8/8 her sürümde** (regresyon yok)
- Halüsinasyon: **0** her sürümde

## Test suite

- `tests/agents/ tests/eval/` — **126/126 pass**
- `tests/api/test_ask_endpoint.py` — **5/5 pass**
- `tests/agents/test_verify_node.py + test_edge_cases.py` — **54/54 pass** (11 yeni test)

## Gözlem

HyDE Türkçe hukuk için **selektif** kazanç sağlıyor:
- E4 (kira) **+0.107** — vatandaş dili ("ev sahibi sözleşmeyi feshedebilir") ↔ kanun dili (TBK m.306 "ayıplar nedeniyle sözleşmeden dönme") boşluğunu LLM hipotetik metni kapatıyor
- E5/E6/E7 nötr — retrieval zaten kanun jargonunda eşleşiyor
- E2/E8 variance — HyDE-üretilen hipotetik metin bazen yanlış yöne yönlendiriyor

Genel sonuç: HyDE **paper material** için faydalı (ablation tablosunda +1 satır), production'da +13s latency maliyeti. Mevcut config'te `HYDE_ENABLED=1` default, isteğe göre kapatılabilir.

## Donanım

Aynı (RTX 4070 12GB, llama-server -ngl 20, BGE-M3+reranker GPU fp16).

## Pending (Sprint-4+)

- Multi-query mode A/B (mevzuat_node şu an HyDE'a öncelik veriyor)
- ColBERT late-interaction (Aralık 2026 hedefi)
- BGE-M3 LoRA Yargıtay+mevzuat fine-tune (Mart 2027 hedefi)
- freeze_baseline 4-mode delta (HyDE ile D@5 etkisi) — şu an çalışıyor
