# ADALET Backend Tam-Sistem Denetimi — 2026-06-04

> 6 uzman-bakış finder (kırmızı-çizgi · retrieval · eval · api-güvenlik · orkestrasyon · pii)
> → her bulgu 3 lensle adversarial doğrulandı (gerçeklik / erişilebilirlik / etki).
> Workflow: `wj3lxe5ep`. **25 ham bulgu → 20 onaylı** (≥2/3 real + etki).
> Doğrulama kalitesi: 5 yanlış-pozitif reddedildi (örn "FABRİKE-eşik production'a bağlı değil"
> → iter-2'de bağlandığı için 0/3 real ile reddedildi).

Durum: ✅ çözüldü · 🔲 backlog. Sıralama: competition_impact → severity.

> **GÜNCELLEME 2026-06-04:** 20 onaylı bulgunun **14'ü çözüldü** (A-E + PII×3 + CI + resilience +
> imkânsız-madde-veto + güvenlik×2 + finalize-Literal). Kalan 6 (debate retry→pass · speculative
> re-scoring · NLI-gold · madde-recall metriği · istatistiksel CI · frontend-Supabase) net-bug DEĞİL,
> **ranking/eşik heuristiği veya araştırma** → calibration/benchmark ÖLÇÜMÜ ile yapılmalı (kör değişiklik
> regresyon riski). Git: a2f8b63 e19c320 9fd633a d929931 62fdf82 c531fc2 6c9e544 62165b2.

## ✅ Çözülenler (high-impact)

| # | Bulgu | Dosya | Commit |
|---|-------|-------|--------|
| A | `_grounded_true_eligibility` süre-eşiğini GLOBAL havuzluyor → ilgisiz snippet uydurma eşiği akıyor | risk_guard.py | a2f8b63 |
| B | Düşük-güven hukuki soru (domain=unknown) verify'ı atlayıp serbest-form chat'e düşüyor | chat.py | a2f8b63 |
| C | `_remove_unsafe_duration_inferences` eligibility varsa deadline-uydurmayı hiç temizlemiyor | draft.py | a2f8b63 |
| D | Multi-Query `sparse_domain`'i geçirmiyor → trafik/icra MQ BM25 sparse kaybı | multi_query.py | e19c320 |
| E | HyDE boş-sparse prefetch'i RRF'i kirletiyor (tuketici/kira/isHukuku) | hyde.py | e19c320 |

## 🔲 Backlog (medium-impact)

1. **PII — OCR metni + case_facts ham PII ile LLM'e + session'a maskesiz** (ask.py, CRITICAL sev).
   image_attachments text mask_pii'siz state'e giriyor → triaj LLM prompt'una TCKN/IBAN; case_facts
   `_persist_turn`'de maskelenmeden session store'a yazılıyor. → persist/LLM öncesi mask_pii.
2. **PII regex format varyantlarını kaçırıyor** (pii.py, HIGH sev). Boşluklu/noktalı TCKN
   ('123 456 789 01'), parantezli/sabit-hat telefon, küçük-harf IBAN ('tr33…', IGNORECASE yok).
3. **STT çıktısında PII tespiti yok** (stt.py, MEDIUM). OCR'da var, STT'de yok — asimetrik.
   STTUploadResponse'a pii_detected ekle, result.text'e mask_pii uygula.
4. **Hiçbir eval/gold harness CI'da değil** (backend-ci.yml, HIGH sev). hallucination/eligibility/
   nli/ragas hiç koşmuyor → metrik regresyonu sessiz geçer. → eval.scorecard --check (LLM'siz) CI'a.
5. **Paralel fan-in retrieval guard'sız → tek hata graph'ı çökertiyor** (emsal.py:43, mevzuat.py:118/
   122/125, HIGH sev). Fallback-dışı exception (RuntimeError/ValueError) tüm /ask'i 500 yapıyor.
   → node gövdesini top-level try/except ile sar, boş refs + errors.append (operator.add reducer var).
6. **answer_risk detektörleri (implausible_article >1100, unsourced_claim) production veto'da yok**
   (answer_risk.py, MEDIUM). layer1_rules madde 1≤no≤99999 kabul ediyor ('madde 5000' geçer).
   → implausible_article_numbers'ı verify_risk_veto'ya bloklayıcı ekle.
7. **Debate retry-LLM kapalıyken tek doğrulanmış claim 'retry'→'pass' yapıyor** (debate.py:79-91,
   MEDIUM). MIN_VERIFIED_CLAIMS_RATIO=0.20 zaten düşükken zayıf-destekli cevaplar pass oluyor.
8. **Speculative search HyDE+MQ'yu yeniden-skorlamadan concat** (speculative_search.py:62-67, MEDIUM).
   _dedup 'ilk gören kazanır' + concat; ortak-rank RRF füzyonu atılıyor, skor ölçekleri karışıyor.
9. **NLI yanlış-pozitif çelişki oranı gerçek mDeBERTa ile test edilmiyor** (nli_tr_eval, MEDIUM).
   gold 28 satır (zayıf); run_nli/build_report hiç CI'da koşmuyor. → gold 80-100, nightly real-model.
10. **Headline retrieval metrikleri madde/kanun yerine 8-yönlü domain'e bakıyor** (eval_run.py:149-166,
    MEDIUM). expected_madde_no/expected_kanun gold MEVCUT ama kullanılmıyor → MRR abartılı.
11. **Smalltalk önceden-hesaplanan yanıt ÖLÜ — chat node yine LLM çağırıyor** (chat.py, MEDIUM).
    triaj smalltalk_response üretiyor ama policy 'chat'e yönlendirip LLM çağırıyor → 3sn gecikme.
    → chat_node'a smalltalk kısa-yolu (out_of_scope gibi).
12. **Eval tablolarında istatistiksel anlamlılık/güven aralığı yok, gold setler küçük** (eval/*, MEDIUM).
    Wilson/bootstrap %95 CI ekle; eligibility(18)/nli(28) büyüt; McNemar baseline-vs-sistem.

## 🔲 Backlog (low-impact)

13. **/metrics + /metrics/latency auth/rate-limit'siz** (main.py:429-467, HIGH sev). İç latans/yapı açık.
14. **conversation_id girdi doğrulaması yok → Redis key injection** (schemas.py:68, HIGH sev).
    DELETE path'te pattern var ama POST body'de yok → `^[A-Za-z0-9_-]+$` ekle.
15. **redirect_to_scope/compose ölü kod + finalize geçersiz Literal 'redirect'** (finalize.py:265,
    MEDIUM). state.py Literal'ında 'redirect' yok ('redirect_to_scope' var) → tip ihlali frontend'e.

## Reddedilenler (yanlış-pozitif, doğrulama ile elendi)
- "FABRİKE-eşik production veto'da yok" (0/3) — iter-2'de bağlandı.
- "Supabase JWKS ağ hatasında sessiz bypass" (0/3) — gerçekte fail-closed.
- "PDF dilekçe senkron handler ASGI blokajı" (0/3).
- "user_meta nested dict prompt-injection" (0/3).
