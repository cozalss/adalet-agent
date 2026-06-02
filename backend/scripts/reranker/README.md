# Faz-4 — Türkçe-Hukuk Reranker Fine-Tune Pipeline

Konuşma-dili sentezli Türkçe cross-encoder reranker eğitim borusu. Amaç: mevcut
`bge-reranker-v2-m3`'ün konuşma-dili TR hukukta güvenilmez olması ("depozito" vs
"güvence bedeli" eş-anlam sorunu — şu an `domain tier-sort` geçici çözüm) yerine,
**gerçek** Yargıtay/özelge kararlarından üretilen triplet'lerle fine-tune edilmiş,
vatandaş diline uyumlu bir reranker.

## Kırmızı çizgi (CLAUDE.md §1, §4)

- **Pozitif kaynak GERÇEK** kararlardan gelir (newmindai BEIR datasetleri + corpus);
  hiçbir madde/karar **uydurulmaz**.
- LLM (Qwen) **yalnız SORU** üretir, kaynak üretmez.
- **8 sivil alan** dışı (ceza + aile) örnekler `_core.is_out_of_scope` ile **elenir**.

## Veri kaynakları (araştırma + adversarial doğrulama — 2026-06-02)

| Dataset | İçerik | Lisans | Rol |
|---------|--------|--------|-----|
| [newmindai/caselaw-retrieval](https://huggingface.co/datasets/newmindai/caselaw-retrieval) | ~1.39k Yargıtay HGK sivil (sorgu→karar) | CC-BY-4.0 | Pozitif çift |
| [newmindai/regulation-retrieval](https://huggingface.co/datasets/newmindai/regulation-retrieval) | ~120k GİB özelge (vergi/idari) | CC-BY-4.0 | Pozitif çift |

Caveat: dataset sorguları resmî "catchword" (konuşma-dili **değil**) → `synth_queries`
ile vatandaş dili köprüsü kurulur.

## Boru hattı (4 adım)

```bash
cd backend

# 1) GERÇEK datasetleri indir → (sorgu, pozitif) çiftleri + negatif havuzu
#    Üretir: data/reranker/pairs.jsonl, corpus.jsonl  (kapsam-dışı elenir)
uv run python -m scripts.reranker.load_sources            # tam set
# uv run python -m scripts.reranker.load_sources --limit 200   # hızlı deneme

# 2) Konuşma-dili soru sentezi (Qwen few-shot + round-trip filtre) — YEREL LLM GEREKİR
#    Üretir: data/reranker/synth_pairs.jsonl
#    Bu kutuda çalışan mod: in-process llamacpp (GGUF + CUDA-DLL trick). Sunucu modu
#    (llamacpp_server) prebuilt binary ister — yoksa llamacpp kullan.
LLM_MODE=llamacpp LLM_MODEL_PATH=./models/Qwen2.5-14B-Instruct-Q5_K_M.gguf \
  uv run python -m scripts.reranker.synth_queries
# --no-roundtrip ile embedder consistency filtresini atla (daha hızlı, daha gürültülü)
# NOT: round-trip embedder'ı + Qwen aynı anda VRAM ister; 12GB GPU'da EMBEDDING_DEVICE=cpu
#      ekleyerek embedder'ı CPU'ya al (Qwen GPU'da kalsın), VRAM çakışmasını önle.

# 3) Hard-negative madenle (resmî + sentez çiftleri birleşir) → eğitim seti
#    Üretir: data/reranker/train.jsonl, val.jsonl  ({query, passage, label})
uv run python -m scripts.reranker.mine_negatives --num-negatives 4
# --cross-encoder  → bge-reranker ile yeniden-skorla (yanlış-negatif eler, daha yavaş)

# 4) Cross-encoder fine-tune (GPU) → models/reranker-tr-legal/
uv run python -m scripts.reranker.train
# --warm-start seroe/bge-reranker-v2-m3-turkish-triplet  (daha güçlü TR başlangıç)
```

## Üretime bağlama

Fine-tune bitince, üretim reranker'ını yerel modele çevir:

```bash
RERANKER_MODEL=models/reranker-tr-legal   # retrieval/reranker.py otomatik kullanır
```

A/B karşılaştırma: `scripts/ab_retrieval_compare.py` ile eski (BAAI/bge-reranker-v2-m3)
vs yeni modeli benchmark üzerinde ölç (regresyon kapısı — kalite düşerse geri al).

## Test

```bash
uv run python -m pytest tests/scripts/test_reranker_core.py -q   # saf çekirdek (24 test)
```

`_core.py` ağ/model gerektirmeden test edilir (scope-filtre, synth temizleme, round-trip,
dedup, split). İndirme + sentez + madenleme + eğitim adımları kullanıcı kutusunda koşar
(HF erişimi + Qwen + GPU). Çıktı `data/reranker/` ve `models/` **gitignore**'da (regenerable).

## Dosyalar

| Dosya | Sorumluluk |
|-------|-----------|
| `_core.py` | Saf, test-edilebilir mantık (scope-filtre, prompt, temizleme, split) |
| `load_sources.py` | HF BEIR → kapsam-filtreli (sorgu, pozitif) + corpus |
| `synth_queries.py` | Qwen few-shot konuşma-dili soru + round-trip consistency filtre |
| `mine_negatives.py` | `mine_hard_negatives` → etiketli-çift train/val |
| `train.py` | `CrossEncoderTrainer` fine-tune (warm-start → drop-in yedek) |
