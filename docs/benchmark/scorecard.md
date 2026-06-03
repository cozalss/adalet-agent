# ADALET — Sıfır-Halüsinasyon Kalkanı Karnesi

> Deterministik (LLM'siz) ölçüm · `uv run python -m eval.scorecard` ile üretilir (üreten commit SHA'sı konsol çıktısında + `eval/runs/scorecard.json`'da).

**Genel durum: ✅ GEÇTİ** — temiz cevap asla reddedilmez (yanlış-veto=0) ve her riskli cevap yakalanır.

## 1. Halüsinasyon kalkanı (içerik-risk detektörleri)

- Vaka: **104** (32 temiz / 72 riskli, adversarial)
- Mikro precision: **1.0** · mikro recall: **1.0**
- Halüsinasyon yakalama (recall): **100%** (%95 Wilson CI [0.949, 1.000])
- **Yanlış-veto (iyi cevabı reddetme): 0/32 (0%)** ← kritik garanti (oran %95 üst-sınır ≤ 10.7%)

| Detektör türü | Precision | Recall | F1 |
|---|---|---|---|
| Uydurma kanun adı | 1.0 | 1.0 | 1.0 |
| Süre/eşik hak-reddi | 1.0 | 1.0 | 1.0 |
| İmkânsız mahkeme dairesi | 1.0 | 1.0 | 1.0 |
| İmkânsız madde no | 1.0 | 1.0 | 1.0 |
| Kaynaksız iddia | 1.0 | 1.0 | 1.0 |

## 2. Süre-uygunluk FABRİKE-eşik ayrımı (kaynak-temelli, deterministik)

Tehlikeli yanlış-çıkarımın ("5 yıldan az tazminat verilmez" = uydurma eşik) DOĞRU bilgilendirmeden ("1 yılın altında kıdem doğmaz" = kaynakta var) ayrımı.

- Vaka: **18** adversarial · precision: **1.0** (%95 CI [0.646, 1.000]) · recall: **0.875** (%95 CI [0.529, 0.978]) · F1: **0.9333** · doğruluk: **0.9444**

> Küçük-N notu: nokta-tahminleri (P=1.0) yanıltabilir; Wilson %95 güven aralıkları örneklem belirsizliğini dürüstçe gösterir. Setler büyüdükçe aralıklar daralır.

## 3. Veri seti kapsamı (test tabanı breadth)

| Set | Açıklama | Vaka |
|---|---|---|
| `hallucination_gold.jsonl` | Halüsinasyon adversarial gold | 104 |
| `eligibility_adversarial.jsonl` | Süre-uygunluk FABRİKE-eşik gold | 18 |
| `verify_gold.jsonl` | Doğrulama (verify) gold | 59 |
| `nli_tr_gold.jsonl` | Türkçe NLI gold | 28 |
| `benchmark_v2.jsonl` | Ana benchmark (v2) | 186 |
| `out_of_scope_cases.jsonl` | Kapsam-dışı (ceza/aile) vakaları | 30 |
| `prompt_injection_cases.jsonl` | Prompt-injection vakaları | 20 |

---

> Bu karne YALNIZ deterministik (kural/regex/eşik-tabanlı) kalkanı ölçer — LLM, GPU, ağ gerektirmez, her commit'te CI'da koşabilir. Gerçek-LLM gerektiren ölçümler (RAG faithfulness, full-pipeline kalite, prompt-injection çıktı kontrolü) ayrı harness'larda koşar (`quality_gate.py`, `ragas_full.py`, `policy_eval.py`).
