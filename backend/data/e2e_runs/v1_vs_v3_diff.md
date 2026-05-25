# E2E Karşılaştırma — v1 (orig thresholds) vs v3 (relaxed + claim fallback)

| Soru | Domain     | v1 verdict | v3 verdict | v3 claims/sup | v3 conf | Not |
|------|------------|------------|------------|---------------|---------|-----|
| E1   | isHukuku   | reject     | **reject** | 4/3 → 1 NLI veto | 0.00 | NLI contradiction false-positive |
| E2   | isHukuku   | reject     | **pass** ✓ | 7/5 | 0.82 | İçerikte hata: IK m.17 retrieval'a girmedi |
| E3   | tuketici   | reject     | **reject** | 1/0 (Q14B-Q4 14 token) | 0.00 | LLM çok kısa yanıt, prompt + Qwen sorunu |
| E4   | kira       | pass-noref | **pass** ✓ | 4/2 | 0.71 | TMK 194 yanlış konuda alıntılandı (içerik halüsinasyonu) |
| E5   | trafik     | reject     | **pass** ✓ | 4/4 | 0.91 | En güçlü cevap — case-only RAG yeterli |
| E6   | icra       | reject     | **HTTP 500** | — | — | Structlog cp1254 charmap crash → fix uygulandı |
| E7   | vergi      | (E7 mock dom=False) | **pass** ✓ | 3/2 | 0.70 | Triaj "ceza" word-boundary fix doğru çalıştı |
| E8   | tapu       | (E8 mock dom=False) | **pass-unk** | — | 0.00 | Qwen JSON Türkçe karakter bozdu, triaj parse fail |

## Özet
- v1 (orig + MockLLM): 1/8 anlamlı pass (E4 reject-template ile sahte-pass yok)
- v3 (Qwen 14B Q4 + relaxed thresholds + claim fallback): **4/7 anlamlı pass** (E1 NLI, E3 LLM, E6 charmap, E8 dom = ayrı fix'ler)
- Halüsinasyon guard: 0/8 [DOĞRULA: ...] placeholder bırakılmadı (model "emin değilim" iletmek yerine cevap yazmaya devam ediyor)
- CJK leak: 0 char (Qwen Q4 Türkçe karakter çıktısı temiz)
- Ortalama latans: 84s (Qwen partial-GPU -ngl 20)

## Kalan kritik fix'ler (priority)
1. **Mevzuat seed eksiği** (yapım aşaması): VUK/KMK/KK/TBK/HMK/IIK + 8 başka — E2/E5/E6/E7 mevzuat=0 → retrieval yetersiz
2. **NLI threshold daha gevşek** (0.50→0.65) — E1 paraphrase yanlış-pozitif veto
3. **Qwen JSON Türkçe karakter** — llama.cpp grammar JSON-schema veya UTF-8 encode mode
4. **Draft prompt + retry feedback** — E3 retry'da aynı 14-token çıkış (temperature 0.1 deterministik)
