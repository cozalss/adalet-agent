# Sprint-4 Hafta 4 — Verifier Hardening Changelog

Önceki: `eval/runs/W3_changes.md`

## Hedef
verify.py 433→<300 satır; RARR-lite 4. katman; Self-RAG fork doğrulama;
adversarial debate testleri; NLI threshold env-override; LLM-based claim
extraction (opt-in).

## Değişiklikler

### W4.1 — verify.py split
- Yeni `agents/verifier_layers.py` (~270 satır):
  - `layer1_rules`, `layer2_fuzzy`, `layer25_lettuce`, `layer3_nli_batch`
  - `pick_evidence`, `pick_evidence_list` helpers
  - `get_verifier`, `get_lettuce` modül-seviye factory (test monkeypatch için)
- `agents/nodes/verify.py` ~210 satır (433'den indi):
  - Sadece orchestrator + verdict aggregation + claim marking
  - Backward-compat alias'lar (`_layer1_rules = layer1_rules` vb.)
  - RARR-lite çağrısı (W4.2)
- Çözülen sorun: test monkeypatch + module-level import binding mismatch
  → `import agents.verifier_layers as _self; _self.get_verifier()` runtime
  lookup ile çözüldü; sonsuz recursion riski yok.

### W4.2 — RARR-lite (4. katman, opt-in)
- Yeni `verifier/rarr.py`:
  - `augment_evidence_batch(claims, refs) -> int`
  - cite_ids olmayan claim'ler için hybrid_search ile ek snippet çek
  - dedup (source_id), Citation formatına çevir, refs'e ekle
  - ENV: `RARR_ENABLED` (default 0), `RARR_TOP_K=3`, `RARR_MAX_CLAIMS=5`
- `agents/nodes/verify.py`:
  - `if RARR_ENABLED: from verifier.rarr import augment_evidence_batch`
  - Layer 4 olarak çağrılıyor (verify çağrısının verdict üretmeden önce)

### W4.3 — Self-RAG fork verification
- `agents/graph.py` zaten doğru: `_route_after_debate` self_rag sinyalini
  okuyor; `self_rag_node` `debate_verdict`'i mutate ediyor.
- Ek değişiklik yapılmadı — mevcut implementasyon test edildi.

### W4.4 — Adversarial debate tests
- Yeni `tests/agents/test_debate_adversarial.py`: 8 test
  - test_debate_preserves_verify_reject_hard
  - test_debate_pass_accepts_verify_pass
  - test_debate_retry_increments_when_below_max
  - test_debate_hard_reject_after_max_retry
  - test_debate_resists_prompt_injection_in_draft
  - test_debate_resists_injection_in_question
  - test_debate_pass_with_disclaimer_pressure
  - test_debate_state_immutability
- Sonuç: 8/8 yeşil

### W4.5 — NLI threshold env-override
- `agents/config.py`:
  ```python
  NLI_ENTAILMENT_THRESHOLD = float(os.getenv("NLI_ENTAILMENT_THRESHOLD", "0.55"))
  NLI_CONTRADICTION_THRESHOLD = float(os.getenv("NLI_CONTRADICTION_THRESHOLD", "0.70"))
  ```
- A/B test prosedürü:
  ```bash
  NLI_CONTRADICTION_THRESHOLD=0.65 uv run python -m eval.freeze_baseline --benchmark v2
  NLI_CONTRADICTION_THRESHOLD=0.70 uv run python -m eval.freeze_baseline --benchmark v2
  NLI_CONTRADICTION_THRESHOLD=0.75 uv run python -m eval.freeze_baseline --benchmark v2
  ```
- Karar: ölçüm Hafta 10 final eval'de yapılacak.

### W4.6 — LLM-based claim extraction (opt-in)
- `agents/nodes/draft.py`:
  - `LLM_CLAIM_EXTRACTION` env flag (default 0)
  - `_extract_claims_llm()` — JSON mode atomic claim extraction
  - Başarısız (JSON parse hata, LLM down) → otomatik regex fallback
  - Regex `_extract_claims()` proven fallback olarak korundu
- Maliyet: ek 1 LLM çağrısı / draft (~1-2s); opt-in çünkü çok dilekçe
  vakalarında değer / maliyet ratio düşük.

## Test Skoru
- **W3 sonu:** 236 / 236
- **W4 sonu:** **244 / 244 yeşil** (+8 yeni adversarial)
- Regression: 0

## Kritik Çözülen Bug'lar (bonus)
1. **Recursion error** — verifier_layers ↔ verify proxy/sync infinite loop;
   `_self` runtime lookup ile çözüldü.
2. **Monkeypatch path mismatch** — test'ler `agents.nodes.verify.get_verifier`
   patch'liyordu ama layer3 `verifier_layers.get_verifier` çağırıyordu;
   path migration ile fixlendi.

## Kullanıcı Tarafından Çalıştırılması Gerekenler

### RARR-lite aktif test
```bash
RARR_ENABLED=1 LLM_MODE=llamacpp_server PYTHONUTF8=1 \
  uv run python -m eval.freeze_baseline --benchmark v2
# Beklenen: verify-augment çalıştığında log "rarr_augmented n_added=X"
```

### LLM claim extraction aktif test
```bash
LLM_CLAIM_EXTRACTION=1 LLM_MODE=llamacpp_server PYTHONUTF8=1 \
  uv run python -m scripts.ask_via_http  # tek soru E2E
# Beklenen: log "draft_claims_llm n_claims=X" — atomik bölünmüş
```

### NLI A/B test (Hafta 10'da yapılacak)
```bash
for T in 0.65 0.70 0.75; do
  NLI_CONTRADICTION_THRESHOLD=$T \
  LLM_MODE=llamacpp_server PYTHONUTF8=1 \
    uv run python -m eval.freeze_baseline --benchmark v2 --modes hybrid,rerank
done
# Karşılaştır eval/runs/v2_w2_*.json — faithfulness vs hatalı-reject oranı
```

## Sonraki
Hafta 5 — Code Quality + Test Infrastructure: mypy --strict, ruff strict,
real-LLM integration suite, pytest --cov ≥ 80%, Yargıtay regression test,
multi-turn E2E.
