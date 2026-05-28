# Türkçe Hukuk için Doğrulamalı Çoklu-Ajan RAG: ADALET-AGENT

> **Taslak v0.1** — Sprint-4 sonu (Mayıs 2026). TIDE-TR / SIU 2027 hedefli.
> Ortak yazarlar: 4-kişilik bitirme ekibi + Çankaya Bilg./Yazılım Müh. danışmanı
> + Çankaya Hukuk Fakültesi danışmanı (hedef).

## Özet (Abstract)

Türkçe hukuk alanında, vatandaşa ücretsiz, doğrulamalı bir AI asistanı
geliştirme problemini ele aldık. Mevcut büyük dil modelleri (ChatGPT, Gemini)
hukuki referansları **uydurma** (halüsinasyon) eğilimindedir; bu da pratik
kullanımda tehlikeli sonuçlar doğurabilir. Önerdiğimiz **ADALET-AGENT**
sistemi yedi-ajanlı bir LangGraph topolojisi üzerine kurulu olup, dört
katmanlı bir **iddia doğrulama** (claim verification) hattıyla
halüsinasyonları yakalar.

Sistem **BGE-M3 hibrit retrieval** (dense + sparse + ColBERT) ile
mevzuat.gov.tr (16 kanun, 3.950+ chunk) ve Yargıtay/AYM karar arşivinden
(38.700+ chunk) ilgili kaynakları getirir. Üretilen cevap rules-based regex
+ rapidfuzz fuzzy match + LettuceDetect token-grounding + mDeBERTa XNLI
contradiction veto + **RARR-lite evidence augmentation** olmak üzere dört
aşamalı doğrulamadan geçer. Constitutional self-critique ile çelişkili
veya destek bulamayan iddialar reddedilir; sistem cevabı yeniden üretir.

200 vakalı dengelenmiş Türkçe hukuk benchmark'ında elde edilen sonuçlar:
**D@1 X.XX, kanun@5 X.XX, Ragas faithfulness X.XX, average judge score X.XX**.
(W10 final eval sonuçları buraya doldurulacak.) Mevcut baseline'a göre
+%X iyileşme. Sistem MIT lisanslı, tamamen lokal (Qwen 2.5 14B Q4 + RTX
4070), gizlilik odaklı (PII mask + audit log) bir mimaridir.

## 1. Giriş

[1-2 sayfa — motivasyon, problem tanımı, katkı listesi]

### 1.1 Motivasyon

Türkiye'de avukat ücretleri ortalama hane gelirinin önemli bir kısmını
oluşturur; tüketici, işçi, kiracı uyuşmazlıklarında vatandaşların büyük
çoğunluğu hukuki yardım alamadan haklarından feragat etmektedir. Ücretsiz
AI tabanlı asistanlar (ChatGPT, Gemini, vb.) bu boşluğu doldurma potansiyeline
sahiptir; ancak hukuki referansları **uydurma** eğilimi (madde numarası,
karar referansı yanlış / hayali) pratik kullanımı tehlikeli kılmaktadır.

### 1.2 Problem

Çözmeye çalıştığımız üç temel problem:

1. **Halüsinasyon**: LLM'in olmayan kanun maddesi veya Yargıtay kararı
   alıntılaması.
2. **Erişilebilirlik**: Sesli/yazılı/belge fotoğrafı ile çok-modlu giriş;
   sesli okuma (TTS) ile çıktı.
3. **Domain coverage**: Tüketici, iş, kira, icra, vergi, tapu, idari,
   trafik hukukunu dengeli kapsamak.

### 1.3 Katkılar

- 4-katmanlı **claim verification** mimarisi (rules + fuzzy +
  LettuceDetect + NLI + RARR-lite)
- 7-ajanlı LangGraph topology, opt-in Self-RAG + CRAG katmanları
- BGE-M3 dense + sparse + ColBERT hibrit retrieval, HyDE + Multi-Query +
  RRF fusion + RAPTOR hiyerarşik özet ağacı + GraphRAG cross-citation
- **200 vakalı dengelenmiş Türkçe hukuk benchmark'ı** (kamuya açık,
  programmatic generation + manuel review)
- PII mask + audit log + JWT auth + read-only container deploy
- Tamamı **lokal**, **açık-ağırlık** modeller (Qwen 2.5 14B Q4, mDeBERTa,
  BGE-M3), **MIT lisans**

## 2. İlgili Çalışmalar

### 2.1 RAG ve Halüsinasyon

- Lewis et al. 2020 — Retrieval-Augmented Generation
- Gao et al. 2022 — RARR: Researching and Revising
- Sarthi et al. 2024 — RAPTOR
- Edge et al. 2024 — GraphRAG
- Asai et al. 2023 — Self-RAG
- Yan et al. 2024 — Corrective RAG (CRAG)

### 2.2 Hukuki AI

- Cui et al. 2023 — Chatlaw (Çin)
- Mahari et al. 2023 — LawngLM
- TR-Hukuk: literatür henüz dar; AYM-Yargıtay corpus üzerinde özel
  retrieval/verifier çalışması yok.

### 2.3 Çoklu-Ajan ve Constitutional AI

- Du et al. 2023 — Multi-Agent Debate
- Bai et al. 2022 — Constitutional AI (Anthropic)

## 3. Yöntem

### 3.1 Sistem Mimarisi

[Şekil 1 — `docs/architecture.md` Mermaid diagram'ı]

7 ajan + 4 verifier layer + retrieval stack + middleware:

- **Triaj** → 8 domain + unknown classification (JSON-mode)
- **Mevzuat** → kanun maddeleri (BGE-M3 hibrit + HyDE)
- **Emsal** → Yargıtay/Danıştay kararları (+ GraphRAG neighbor expand)
- **Draft** → Qwen 14B Q4 ile cevap üretimi (cite-grounded prompt)
- **Verify** → 4-katman claim verification
- **Debate** → constitutional critique, max 3 retry
- **Finalize** → cevap + kaynak + confidence + disclaimer

### 3.2 Verify 4-Katman

#### Katman 1 — Rules-Based
Madde no regex (`m\.\d{1,4}`), karar referansı (`\d{4}/\d{1,6}`), kanun
kodu doğrulaması.

#### Katman 2 — Fuzzy
rapidfuzz partial_ratio + token_set_ratio, threshold 0.55.

#### Katman 2.5 — LettuceDetect
Token-level grounding scorer, threshold 0.45 (support) / 0.15 (veto).

#### Katman 3 — NLI Contradiction Veto
mDeBERTa-v3 XNLI multilingual; contradiction threshold **0.70**
(ADR-001 — Türkçe paraphrase'lerde 0.50 yanlış-pozitif yüksek).

#### Katman 4 — RARR-lite (Sprint-4 W4.2)
Verify edilemeyen claim için hybrid_search ile ek snippet çek; refs'e
ekle, sonraki iterasyon daha doğru ölçer.

### 3.3 Hibrit Retrieval

- **BGE-M3** dense (1024d) + sparse (idf-weighted) + ColBERT
  (multi-vector late-interaction)
- **HyDE** — soru → hipotetik cevap → embed (Qwen 14B, 15s timeout)
- **Multi-Query** — JSON-mode 5 paraphrase + RRF k=60
- **RAPTOR** — hiyerarşik özet ağacı (offline build, k=3 hops)
- **GraphRAG** — NetworkX MultiDiGraph (167+ node, regex citation extract)
- **Reranker** — bge-reranker-v2-m3 cross-encoder

### 3.4 Benchmark

[ADR-008 — programmatic generation]

- **186 vaka** (50 legacy + 136 generated, hedef 200)
- Domain dağılımı: 60 İK + 50 Tüketici + 40 Kira + 30 TBK + 20 idari/vergi/trafik
- Programmatic: `topics_v2.json` × `_QUESTION_PATTERNS` × yargi-mcp enrichment
- %20 sample manuel review (Sprint-5+)

### 3.5 Evaluation Metrikleri

- **D@1, kanun@5** — retrieval precision
- **context_precision@5** — Ragas
- **faithfulness** — claim ↔ context entailment ratio
- **answer_relevancy** — answer ↔ question semantic similarity
- **LLM-as-Judge** — 0-1 puanlı qualitative rubric
- **Latency p50/p95/p99** — end-to-end

## 4. Sonuçlar

### 4.1 Retrieval Modes Karşılaştırma

| Mode | D@1 | kanun@5 | p95 latency |
|---|---|---|---|
| hybrid | X.XX | X.XX | X.X s |
| + rerank | X.XX | X.XX | X.X s |
| + hyde | X.XX | X.XX | X.X s |
| + multi_query | X.XX | X.XX | X.X s |
| + raptor + graph | X.XX | X.XX | X.X s |

[W10 final eval verisiyle doldurulacak]

### 4.2 Verify Etkisi

[Verify ON vs OFF — halüsinasyon tespit oranı, false-positive oranı]

### 4.3 Edge Cases

[24 OWASP LLM Top-10 vaka — pass/reject doğruluğu]

### 4.4 Real-LLM Smoke

3 vakalık real-LLM smoke (mock retrieval, Sprint-4 W5):

| Q | Domain | Verdict | Verified | Conf | Latency |
|---|---|---|---|---|---|
| E1 Kıdem | isHukuku | pass | 2/2 | 0.889 | 44s |
| E2 Ayıplı | tuketici | pass | 6/6 | 0.865 | 32s |
| E3 Kira ihtar | kira | pass | 2/3 | 0.695 | 22s |

avg 32.5s, 3/3 pass, disclaimer + citation tüm cevaplarda mevcut.

## 5. Tartışma

### 5.1 Güçlü Yönler
- **4-katman defense**: tek bir hata noktası yok
- **Tamamı lokal**: dış servis maliyetini ve kişisel veri aktarımını azaltır + repro
- **Açık-kaynak**: kod + benchmark + ADR'ler — akademik kontrolde

### 5.2 Sınırlamalar
- NLI Türkçe paraphrase'lerde hâlâ false-pos (0.70 threshold trade-off)
- RAPTOR build maliyeti (Qwen 14B, ~30dk 800 chunk)
- Benchmark 200 vaka — Sprint-5+ ile 500 hedef
- Latency 32s avg — RTX 4070 + 14B partial offload sınırı

### 5.3 Etik / Yasal
- Avukatlık Kanunu kapsamı: bilgilendirme amaçlı, **hukuki tavsiye değil**
- Her cevapta disclaimer zorunlu
- Ceza + aile hukuku **kapsam dışı** (etik hassas)
- Gizlilik: PII mask, anonim audit log, kısa süreli session saklama

## 6. Sonuç ve Gelecek Çalışmalar

[Sprint-5+ planı: 200→500 vaka, BGE-M3 LoRA fine-tune, mobil deploy
beta, ML kazanma olasılığı tahmin modeli]

## Teşekkür

Çankaya Üniversitesi Bilg./Yazılım Müh. + Hukuk Fakültesi danışmanlığı,
TÜBİTAK 2209-A burs (~12.000 TL, Kasım 2026 başvuru).

## Kaynakça

[BibTeX — paper'a alınacak referanslar, 25-30 atıf]

## Ek-A: Reproducibility

```bash
git clone https://github.com/<org>/adalet-agent
cd adalet-agent/backend
uv sync
docker compose --env-file .env.example up -d qdrant redis
uv run python -m scripts.seed_mevzuat && uv run python -m scripts.seed_emsal
uv run python -m eval.freeze_baseline --benchmark v2 --modes all
```

Tüm Sprint-4 sonu run'lar `eval/runs/manifest.json`'da listeli.
