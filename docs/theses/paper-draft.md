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

186 vakalı Türkçe hukuk benchmark'ında (8 sivil alan, BGE-M3 hibrit) ölçülen
retrieval sonuçları: **domain@1 %81.7, keyword-recall@5 %79.6, P95 retrieval
gecikmesi 69 ms**. Doğrulama katmanının ayırt etme gücü (8 soru, gerçek Qwen):
LLM iddialarının ortalama **%58.1'i** kaynakla token-düzeyinde doğrulanamıyor
(claim-support: verify AÇIK %41.9 vs KAPALI %100). Ragas faithfulness ve
LLM-judge skorları henüz ölçülmedi (gerçek-LLM toplu koşum bekliyor — Üye 4).
Sistem MIT lisanslı, tamamen lokal (üretim Qwen3.5-9B; rapor edilen ablation
ölçümleri Qwen 2.5 14B Q5_K_M / RTX 4070), gizlilik odaklı (PII mask + audit
log) bir mimaridir.

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
- **186 vakalı dengelenmiş Türkçe hukuk benchmark'ı** (kamuya açık,
  programmatic generation + manuel review)
- PII mask + audit log + JWT auth + read-only container deploy
- Tamamı **lokal**, **açık-ağırlık** modeller (üretim Qwen3.5-9B; ablation
  Qwen 2.5 14B, mDeBERTa, BGE-M3 / Mursit-Base-TR), **MIT lisans**

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

8 ajan (Tahmin dahil, opt-in) + V2 policy katmanı + 4 verifier layer + retrieval stack + middleware:

- **Triaj** → 8 domain + unknown classification (JSON-mode)
- **Mevzuat** → kanun maddeleri (BGE-M3 hibrit + HyDE)
- **Emsal** → Yargıtay/Danıştay kararları (+ GraphRAG neighbor expand)
- **Draft** → lokal Qwen (üretim Qwen3.5-9B) ile cevap üretimi (cite-grounded prompt)
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

v2 benchmark, 186 vaka, 8 sivil domain, BGE-M3 dense+sparse + RRF füzyon
(`eval_run --version v2 [--rerank]`). "kw-recall@5" = ground-truth anahtar
(madde/kanun) top-5'te ∈.

| Mode | domain@1 | kw-recall@5 | retrieval P95 |
|---|---:|---:|---:|
| hybrid (BM25+dense+RRF) | %81.7 | %79.6 | 69 ms |
| + rerank (BGE-reranker-v2-m3) | %81.2 | %78.2 | 12.18 s |
| + hyde | ölçülmedi¹ | — | — |
| + multi_query | ölçülmedi¹ | — | — |
| + raptor + graph | ölçülmedi² | — | — |

¹ HyDE/multi_query gerçek LLM gerektirir (stokastik sorgu genişletme) — gerçek-LLM GPU
koşumu bekliyor (Üye 4). ² RAPTOR/GraphRAG offline-build gerektiren opt-in modüllerdir;
üretim default'unda kapalı, henüz ölçülmedi.

**Bulgu:** Cross-encoder rerank domain@1'de kazanç sağlamıyor (%81.7→%81.2) ve
kw-recall'ı iyileştirmiyor; buna karşın ~10× gecikme getiriyor (ort. 260 ms→2.78 s,
P95 69 ms→12.18 s). Bu, "cross-encoder Türkçe konuşma-diline zayıf → domain-öncelikli
tier-sort" tasarım kararını sayısal doğrular. NOT: üretim embedder'ı Mursit-Base-TR'ye
geçti (kanun@5 +7pp, P95 −42% — ayrı ölçüm); bu tablo BGE-M3 ablation referansıdır.

### 4.2 Verify Etkisi

8 vatandaş sorusu, doğrulama katmanı AÇIK vs KAPALI, gerçek Qwen 2.5 14B
(`eval/verify_ablation.py`):

| Metrik | verify AÇIK | verify KAPALI |
|---|---:|---:|
| Ort. claim-support | %41.9 | %100 |
| Verdict-flip (block-rate) | %0 (8/8 pass) | — |

Fark = **+58.1 puan**: LLM iddialarının ortalama %58'i kaynakla token-düzeyinde
doğrulanmıyor (KAPALI iken hepsi sorgusuz "supported"). "İddia-doğrulamalı = uydurmaz"
iddiasının doğrudan sayısal kanıtı. **Dürüst nüans:** bu temiz/kapsam-içi sorularda
verify cevabı REDDETMİYOR, claim-düzeyinde ~%58 iddiayı "kaynaksız" işaretliyor; RED
gücü çelişki/adversarial girdide (§4.3) devreye girer.

### 4.3 Edge Cases

24 OWASP LLM Top-10 vakası (PI/jailbreak/PII/excessive-agency/overreliance) — runner +
CLI hazır (`eval/edge_cases.py`), gerçek-LLM GPU koşumu bekliyor (Üye 4). Verify'ın RED
gücü burada ölçülecek (adversarial/çelişki girdi). [Ölçüm bekliyor.]

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
- Benchmark 186 vaka — Sprint-5+ ile 500 hedef
- Latency 32s avg (real-LLM smoke, Qwen 2.5 14B partial offload, §4.4) — üretim Qwen3.5-9B'ye geçti, yeniden ölçüm kuyrukta

### 5.3 Etik / Yasal
- Avukatlık Kanunu kapsamı: bilgilendirme amaçlı, **hukuki tavsiye değil**
- Her cevapta disclaimer zorunlu
- Ceza + aile hukuku **kapsam dışı** (etik hassas)
- Gizlilik: PII mask, anonim audit log, kısa süreli session saklama

## 6. Sonuç ve Gelecek Çalışmalar

[Sprint-5+ planı: 186→500 vaka, HyDE/multi_query/RAPTOR modlarının gerçek-LLM
ölçümü, Ragas faithfulness toplu koşum, edge-case (OWASP) GPU koşumu, gold eval-set
(insan-etiketli, Cohen's κ), mobil deploy beta, dava-sonucu tahmin modeli (BERT-TR f1 0.825)]

## Teşekkür

Çankaya Üniversitesi Bilg./Yazılım Müh. + Hukuk Fakültesi danışmanlığı,
TÜBİTAK 2209-A burs (~12.000 TL, Kasım 2026 başvuru).

## Kaynakça

[BibTeX — paper'a alınacak referanslar, 25-30 atıf]

## Ek-A: Reproducibility

```bash
git clone https://github.com/<org>/adalet-agent   # repo URL henüz TBD (açık-kaynak launch'ta)
cd adalet-agent/backend
uv sync
docker compose --env-file .env.example up -d qdrant redis
# Seed — mevzuat (kanun maddeleri) + emsal (Yargıtay/Danıştay, scripts.seed orkestratörü):
uv run python -m scripts.seed_mevzuat
uv run python -m scripts.seed --court all --domain all --limit-per-domain 1000
# Retrieval baseline — LLM'siz modlar (hyde/multi_query gerçek LLM gerektirir → ayrı koşum):
uv run python -m eval.freeze_baseline --benchmark v2 --modes hybrid,rerank
```

> Komut doğruluğu (repro-kritik): `eval.freeze_baseline` geçerli mode'ları
> `hybrid,rerank,hyde,multi_query`'dir ("all" KABUL EDİLMEZ). Emsal seed ayrı bir
> `seed_emsal` script'i değil, `scripts.seed` orkestratörüdür (`--court/--domain/--limit-per-domain`).
> Sprint-4 sonu run'lar `eval/runs/` altında JSON olarak kayıtlı.
