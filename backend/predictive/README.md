# predictive — Dava Sonucu Tahmin Modeli (Sprint-7/8, Mart-Nisan 2027)

> **Durum (2026-05-26):** Tasarım ve plan TAM dökümante; eğitim verisi toplama
> ve fine-tune Sprint-7/8'de. Bu README'yi okuyan Üye 4 (ML lead) doğrudan
> uygulamaya başlayabilir. Bitirme jürisinde "scope kasıtlı dışı, plan hazır,
> Sprint-7/8'de implement" diye savunulur.

## 🎯 Hedef

ADALET-AGENT'a **opsiyonel 8. ajan** olarak eklenecek `tahmin_node`:
- **Girdi**: kullanıcı sorusu + domain + getirilen mevzuat/emsal kaynaklar
- **Çıktı**: `(verdict_class, confidence, similar_cases[])` — vatandaşa "Bu davada %X kazanma şansın var" tahmini
- **Konum**: `Draft → Verify → Debate → Tahmin (opt-in) → Finalize`

**Neden değerli**: Verify halüsinasyonu engelliyor, ama vatandaş "açsam kazanır mıyım?" diye sormaya devam ediyor. Tahmin modeli bu boşluğu kapatır.

**Neden Sprint-7/8**: Sıfır halüsinasyon (verify+debate) hukukta KRİTİK ve tamam; tahmin "katma değer". Önce sağlam temel, sonra tahmin.

---

## 🏗️ Teknik Tasarım (Hazır — Implement Bekliyor)

### Model Mimarisi

```
Yargıtay karar metni (max 4096 token)
              │
              ▼
   ┌──────────────────────┐
   │  dbmdz/bert-base-    │  ← Base: Turkish BERT
   │  turkish-cased       │     110M params
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │  Pooler (CLS token)  │
   │  → 768-d embedding   │
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │  Dropout(0.1)        │
   │  Linear(768 → 3)     │  ← Head: 3-class
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │  Softmax + Platt     │  ← Calibration
   │  scaling             │
   └──────────┬───────────┘
              ▼
  {kazandi: 0.71, kaybetti: 0.23, kismi: 0.06}
```

### Sınıflar (3-class)
- **kazandi**: Davacı/talepte bulunan haklı çıktı
- **kaybetti**: Reddedildi, davacı haklı çıkamadı
- **kismi**: Kısmen kabul, kısmen ret

Binary (won/lost) yerine 3-class çünkü gerçek davaların ~%30'u kısmi kabul.

---

## 📊 Veri Toplama Stratejisi

### Hedef: 10.000 Etiketli Yargıtay Kararı

```
Toplam: 10.000 vaka
├─ Tüketici Hukuku    1.500
├─ İş Hukuku          1.800
├─ Kira Hukuku        1.200
├─ İcra-İflas         1.000
├─ Trafik/Sigorta       800
├─ Vergi                800
├─ Tapu/Gayrimenkul     900
├─ İdari/Vergi        1.000
└─ Karma                1.000
```

### Etiketleme Protokolü (3 Aşama)

#### Aşama 1: Regex + Heuristic (Otomatik, ~%70 doğru)
```python
# scripts/predictive/auto_label.py
PATTERNS = {
    "kazandi": [r"kabulüne karar verilmiş", r"davanın kabulüne", r"talep kabul edilmiş"],
    "kaybetti": [r"reddine karar verilmiş", r"davanın reddi", r"talep reddedilmiş"],
    "kismi": [r"kısmen kabul", r"kısmen kabulüne", r"kısmen reddine"],
}
```
- Yargıtay karar sonuç bölümünden regex çıkarımı
- 10.000 candidate label ~1 saat

#### Aşama 2: Inter-Annotator Agreement (3 Anotatör)
- 200 vakalık altküme: 3 hukuk öğrencisi/akademisyen bağımsız etiketler
- Cohen's Kappa ≥ 0.75 hedef
- Eğer uyum düşükse → etiketleme rehberi revize, tekrar
- Çankaya Hukuk Fakültesi'nden ortak danışmanlık (hedef)

#### Aşama 3: LLM-Assisted Etiketleme (Düşük Güven İçin)
```python
# Auto label confidence < 0.8 için Qwen 14B'ye sor
prompt = f"""Karar metni: {text}
Bu davada hangisi oldu? (kazandi/kaybetti/kismi)
Cevabını JSON: {{"verdict": "...", "reasoning": "..."}}"""
```
- Qwen + heuristic ensemble
- İnsan validate sample (her 100'de 10)

---

## 🧪 Fine-Tune Pipeline

### Setup
```python
# predictive/train.py
from transformers import (
    BertTokenizer, BertForSequenceClassification,
    Trainer, TrainingArguments,
)

model = BertForSequenceClassification.from_pretrained(
    "dbmdz/bert-base-turkish-cased",
    num_labels=3,
    problem_type="single_label_classification",
)

training_args = TrainingArguments(
    output_dir="./checkpoints",
    num_train_epochs=3,
    per_device_train_batch_size=16,
    learning_rate=2e-5,
    warmup_ratio=0.1,
    weight_decay=0.01,
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model="f1_macro",
    fp16=True,  # RTX 4070 ile mixed precision
    gradient_checkpointing=True,
)
```

### Splits
- Train: 8.000 (80%)
- Validation: 1.000 (10%)
- Test (holdout): 1.000 (10%)

### GPU Saatleri
- RTX 4070 12GB + fp16 + grad checkpointing
- ~6 saat × 3 epoch = **~18 saat eğitim**
- Sprint-7'nin 1 günü buna ayrılır

---

## 📐 Hedef Metrikler

| Metrik | Hedef | Niye |
|---|---|---|
| **F1 macro** | ≥ 0.75 | Sınıf dengesizliği var (kismi az) |
| **Accuracy** | ≥ 0.78 | Genel kalite |
| **ECE (calibration)** | ≤ 0.05 | Vatandaşa %X dediğin gerçekten %X olsun |
| **Brier Score** | ≤ 0.20 | Olasılık tahmini kalitesi |
| **Inference latency p95** | ≤ 200ms | BERT-base CPU üzerinde |
| **VRAM (inference)** | < 2 GB | Qwen ile aynı GPU'da çalışsın |

### Calibration (Platt Scaling)
```python
# predictive/calibrate.py
from sklearn.calibration import CalibratedClassifierCV

# Logit'leri sigmoid + Platt fit ile düzelt
calibrator = CalibratedClassifierCV(model_wrapper, method="sigmoid", cv=5)
calibrator.fit(X_val, y_val)
```
"%80 kazanırsın" demek, **gerçekten %80 kazanılan davalar grubunda** olmak demek.

---

## 🔌 Backend Entegrasyon Tasarımı

### 1. Yeni Ajan Node
```python
# agents/nodes/tahmin.py
import os
from agents.state import AgentState, Prediction
from core.observability import observe_node
from predictive.inference import predict_outcome

PREDICTIVE_ENABLED = os.getenv("PREDICTIVE_ENABLED", "0") in {"1","true","yes"}

@observe_node(name="tahmin")
async def tahmin_node(state: AgentState) -> dict:
    """Draft sonrası, Verify ile paralel — kazanma olasılığı."""
    if not PREDICTIVE_ENABLED:
        return {"prediction": None}
    question = state["question"]
    refs = state.get("emsal_refs", [])
    if not refs:
        return {"prediction": None}
    # En benzer 5 emsal karar üzerinde tahmin
    similar_texts = [r.text for r in refs[:5]]
    prediction = await predict_outcome(question, similar_texts)
    return {"prediction": prediction}
```

### 2. State Schema Eklenmesi
```python
# agents/state.py
class Prediction(NamedTuple):
    verdict_class: Literal["kazandi", "kaybetti", "kismi"]
    confidence: float  # 0.0-1.0, calibrated
    similar_cases: list[str]  # doc_id'ler
    reasoning: str  # human-readable

class AgentState(TypedDict, total=False):
    ...
    prediction: Prediction | None
```

### 3. API Response Schema
```python
# api/schemas.py
class PredictionSchema(BaseModel):
    verdict_class: Literal["kazandi", "kaybetti", "kismi"]
    confidence: float
    similar_case_ids: list[str]
    reasoning: str
    disclaimer: str = "Bu tahmin geçmiş Yargıtay kararlarından öğrenilmiş bir modeldir, mahkeme garantisi değildir."

class AskResponse(BaseModel):
    ...
    prediction: PredictionSchema | None = None
```

### 4. Graph Topology Değişikliği
```python
# agents/graph.py
if PREDICTIVE_ENABLED:
    g.add_node("tahmin", tahmin_node)
    g.add_edge("draft", "tahmin")   # paralel verify ile
    g.add_edge("tahmin", "finalize")
```

---

## 🎓 Akademik Değer (Tez Çerçevesi)

### Üye 4 Tez Başlığı
"Türkçe Hukuk için BERT-Tabanlı Dava Sonucu Tahmin Modeli ve Çoklu-Ajan Mimarisine Entegrasyonu"

### Katkılar
1. **İlk Türkçe legal outcome prediction benchmark'ı** — 10K labeled corpus açık kaynak (paper'a referans)
2. **Calibrated confidence** — sadece accuracy değil, ECE-optimize
3. **Multi-agent integration** — tek başına sınıflandırıcı değil, RAG + verify ile ensemble
4. **Cohen's Kappa raporu** — etiketleme protokolü akademik standartta

### Karşılaştırma (Paper Bölümü)
- vs. ChatGPT few-shot Türkçe (baseline)
- vs. Random Forest + TF-IDF (klasik)
- vs. Sade BERT-TR (ablation: head value)
- vs. BERT-TR + Platt (calibration value)

### Yayım Hedefi
- **TIDE-TR** (Türkçe doğal dil işleme konferansı, Eylül 2027)
- **SIU 2027** (Sinyal İşleme ve İletişim Uygulamaları Kurultayı)
- Stretch: **ACL Findings** (EMNLP/ACL 2027, İngilizce)

---

## 🛣️ Sprint-7/8 Detay Plan (8 Hafta)

### Hafta 1 (Sprint-7 W1) — Veri Pipeline
- [ ] `scripts/predictive/fetch_yargitay_outcomes.py` — Bedesten + yargi-mcp ile 10K karar metni
- [ ] `scripts/predictive/auto_label.py` — regex/heuristic ilk etiket (≥7K)
- [ ] `data/predictive/raw_v1.jsonl` — ham veri

### Hafta 2 — Anotasyon Protokolü
- [ ] 200 vaka × 3 anotatör (Çankaya Hukuk Fak.)
- [ ] Cohen's Kappa hesabı + uyumsuzluk review
- [ ] Etiketleme rehberi (`docs/predictive/annotation_guide.md`)

### Hafta 3 — LLM-Assisted Validation
- [ ] Düşük güven (~3K) için Qwen ile re-label
- [ ] İnsan validate sample (300 vaka)
- [ ] `data/predictive/labeled_v2.jsonl` (10K)

### Hafta 4 — Fine-Tune Pipeline
- [ ] `predictive/train.py` (HuggingFace Trainer)
- [ ] Hyperparameter sweep (lr ∈ {1e-5, 2e-5, 5e-5}, epoch ∈ {2,3,5})
- [ ] Best model checkpoint → `predictive/checkpoints/best/`

### Hafta 5 (Sprint-8 W1) — Calibration + Eval
- [ ] `predictive/calibrate.py` (Platt + temperature scaling A/B)
- [ ] Holdout test (1K)
- [ ] Reliability diagram + ECE rapor

### Hafta 6 — Inference Wrapper
- [ ] `predictive/inference.py` — async API, FastAPI-ready
- [ ] Latency benchmark (p50/p95)
- [ ] Docker container (optimized inference)

### Hafta 7 — Backend Integration
- [ ] `agents/nodes/tahmin.py` — yeni node
- [ ] `agents/state.py` Prediction TypedDict
- [ ] `api/schemas.py` PredictionSchema
- [ ] `agents/graph.py` PREDICTIVE_ENABLED toggle
- [ ] Tests: `tests/predictive/` + `tests/agents/test_tahmin_node.py`

### Hafta 8 — Ablation + Paper Material
- [ ] `eval/predictive_ablation.py` — RAG vs RAG+Tahmin
- [ ] Bitirme jürisi için demo notebook
- [ ] Paper draft (`docs/theses/tez-4-predictive-paper-draft.md`)

---

## 📦 Dosya Yapısı (Sprint-7/8'de oluşacak)

```
backend/predictive/
├── __init__.py
├── README.md (this file)
├── train.py            # Fine-tune entry
├── inference.py        # Async API wrapper
├── calibrate.py        # Platt scaling
├── data_loader.py      # JSONL → torch.Dataset
├── checkpoints/        # Model artifacts (gitignore)
│   └── best/
└── tests/
    └── test_inference.py

backend/scripts/predictive/
├── fetch_yargitay_outcomes.py
├── auto_label.py
└── llm_validate.py

backend/data/predictive/
├── raw_v1.jsonl        # 10K karar metni
├── labeled_v2.jsonl    # 10K etiketli
└── splits/
    ├── train.jsonl
    ├── val.jsonl
    └── test.jsonl

backend/eval/runs/
└── predictive_ablation_<date>.md

docs/predictive/
├── annotation_guide.md
└── decisions/
    └── ADR-009-predictive-model.md

docs/theses/
└── tez-4-predictive-paper-draft.md
```

---

## ⚠️ Riskler ve Düşüş Senaryoları

| Risk | Olasılık | Düşüş |
|---|---|---|
| 10K etiket toplama Cohen's Kappa 0.6'dan az | Orta | Daha sıkı rehber, 5K ile fine-tune yeterli baseline |
| Çankaya Hukuk Fak. işbirliği gecikir | Yüksek | Yalnız LLM-assisted etiketleme + holdout sample insan-onayı |
| Fine-tune zamanı 18h yetmez (overfit) | Orta | LoRA adapter (parametre azalt) — 3-4 saat |
| BERT-TR Yargıtay metnine cevap vermez | Düşük | XLM-R veya mT5 fallback — aynı pipeline |
| Inference p95 200ms aşar | Düşük | Quantize (INT8) veya distillation |
| Verify+tahmin conflict (çelişen output) | Orta | Tahmin sadece display, verify hard gate kalır |

---

## ✅ Bitirme Jüri'sine Konuşma Noktaları

> "Predictive ajanı kasıtlı olarak Sprint-7/8'e ertelendi çünkü hukukta **sıfır halüsinasyon** önceliği `verify+debate` zincirini Sprint-3+'da tamamlamak şartıydı. Bugün 7-ajan RAG ekibi 3/3 real Qwen smoke pass veriyor. Tahmin modeli için 8 haftalık plan dökümante, 10K karar etiketleme protokolü hazır, BERT-TR fine-tune pipeline tasarlandı, calibration yöntemi seçildi (Platt scaling, ECE ≤ 0.05 hedef), backend entegrasyon noktası belirlendi (8. ajan `tahmin_node`). Sprint-7 başında veri toplama scripti çalışır, Sprint-8 sonunda ablation raporu hazır olur."

Jüri "predictive nerede demo?" derse cevap:
- "Predictive demo Sprint-8 sonu (Nisan 2027). Şu an plan + tasarım + entegrasyon noktası tam dökümante. RAG zinciri tamam, halüsinasyon kapısı 24/24 pass, tahmin opsiyonel toggle ile eklenecek."

---

## 🔗 İlgili Dokümanlar

- `../CLAUDE.md` §13 — proje yol haritası
- `docs/theses/tez-4-multiagent.md` — Üye 4 tez taslağı (bu README ile sync)
- `docs/decisions/ADR-009-predictive-model.md` — mimari karar kaydı (Sprint-7'de)
- `data/eval_benchmark/benchmark_v2.jsonl` — eğitim için 30 örnek vatandaş sorusu mevcut

**Güncelleme**: 2026-05-26 — full Sprint-7/8 plan eklendi (Üye 4 implementasyona doğrudan başlayabilir).
