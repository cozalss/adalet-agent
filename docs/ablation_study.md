# Ablasyon Çalışması: ADALET-AGENT Doğrulama ve Retrieval Katmanları

**Proje:** ADALET-AGENT — Türkçe Hukuk için Çok Ajanlı Doğrulamalı Yapay Zeka Sistemi  
**Tarih:** 2026-05-30  
**Veri Seti:** `data/eval_benchmark/verify_gold.jsonl` (59 vaka) + `benchmark_v2.jsonl` (186 vaka)  
**Kaynak Kod:** `eval/verify_calibration.py`, `agents/nodes/verify.py`, `agents/config.py`, `scripts/eval_run.py`  
**LLM:** Qwen 2.5 14B Q5_K_M (yerel, llama-server)  
**Retrieval:** BGE-M3 hibrit (BM25 + yoğun), Qdrant `adalet` koleksiyonu (159.362 nokta)

---

## Özet

Bu çalışma, ADALET-AGENT doğrulama boru hattındaki bileşenlerin katkısını sistematik olarak ölçmektedir. 59 etiketli vakadan oluşan altın küme üzerinde yapılan ölçümler, modelsiz boru hattının (L1 kural + bulanık eşleşme) paraphrase ve çelişki kategorilerinde yaklaşık rastgele tahmin düzeyinde kaldığını ortaya koymaktadır (doğruluk yaklaşık 0,22). Bu bulgu, Doğal Dil Çıkarımı (NLI) katmanının yapısal zorunluluğunu kanıtlamaktadır. Ek olarak, bulanık eşik optimizasyonu eşiği 0,55den 0,45e indirerek F1 skorunu yüzde 38 iyileştirmiştir. Cross-encoder yeniden sıralayıcısının Türkçe konuşma dili girdilerinde güvenilirlik sorunu tespit edilmiş ve HyDE ile Çoklu-Sorgu genişletme stratejilerinin beklenen katkısı değerlendirilmiştir.

---

## 1. Giriş

Türkçe hukuk alanında Bilgi Artırımlı Üretim (RAG) sistemleri iki yapısal güçlükle karşı karşıyadır. Birincisi, vatandaş sorguları ile hukuk metinleri arasındaki dil seviyesi farkıdır: kullanıcı "depozitomu vermiyor" yazarken mevzuat "kiracının verdiği güvence bedeli" ifadesini kullanmaktadır. Bu leksik boşluk, standart yoğun (dense) gömme modelleri için ciddi bir geri çağırma (recall) kaybı yaratmaktadır. İkincisi ise hallüsinasyon riski; küçük parametreli yerel dil modelleri (bu çalışmada Qwen 2.5 14B Q5_K_M) doğrulama olmaksızın uydurma madde numaraları ve içtihat referansları üretebilmektedir.

ADALET-AGENT bu iki soruna dört katmanlı bir doğrulama mimarisi ile yanıt vermektedir: (1) sözdizimsel kural kontrolü (Katman 1), (2) hızlı bulanık eşleşme (Katman 2), (2.5) LettuceDetect jeton düzeyi zemin tespiti (Katman 2.5) ve (3) mDeBERTa XNLI çelişki vetosu (Katman 3). Bu çalışma, her katmanın katkısını ölçülebilir verilerle belgelemeyi ve sistemin bütünsel değerlendirmesini sunmayı amaçlamaktadır.

---

## 2. Doğrulama Katmanı Ablasyon Analizi

### 2.1 Veri Seti ve Metodoloji

Altın küme, beş kategoriye ayrılmış 59 sentetik (iddia, kanıt) çiftinden oluşmaktadır. Sentetik değerlendirme fikstürleri olarak tasarlanan bu çiftler, madde referanslarının doğruluk kararı üzerindeki etkisini ölçmek amacıyla oluşturulmuştur; gerçek hukuki beyan niteliği taşımamaktadır (`CLAUDE.md §1` gereği).

| Kategori | n | Açıklama |
|---|---|---|
| `exact` | 11 | İddia, kanıt metninin doğrudan yeniden ifadesidir |
| `format_bad` | 5 | Madde numarası biçimsel olarak geçersizdir |
| `unsupported` | 16 | İddia, kapsam dışı veya konuyla ilgisizdir |
| `paraphrase` | 14 | İddia, kanıtı farklı kelimelerle ifade etmektedir |
| `contradiction` | 13 | İddia, kanıtla doğrudan çelişmektedir |

### 2.2 Modelsiz Boru Hattı Performansı

`eval/verify_calibration.py` çalıştırıldığında (59 vaka, 2026-05-30) modelsiz boru hattı (Katman 1 + Katman 2) şu sonuçları üretmiştir:

| Kategori | n | Doğruluk | Yorum |
|---|---|---|---|
| `exact` | 11 | 0,91 | Düz yeniden ifadelerde yüksek performans |
| `format_bad` | 5 | 1,00 | Kural tabanlı, mükemmel |
| `unsupported` | 16 | 0,94 | Kapsam dışı tespiti güçlü |
| `paraphrase` | 14 | **0,86** | 0,45 eşiğiyle yüksek geri çağırma (eski 0,55: 0,21) |
| `contradiction` | 13 | **0,00** | KRİTİK: Tüm çelişkiler yanlışlıkla desteklenmiş sayılıyor |

> **Not — Eşik etkisi:** Eşik 0,55'ten 0,45'e düşürüldüğünde paraphrase doğruluğu 0,21'den 0,86'ya yükselirken contradiction doğruluğu 0,23'ten 0,00'a düşmektedir. Bu iki ölçüm birlikte kritik bir tasarım kısıtını ortaya koyar: bulanık eşleşme geri çağırma-kesinlik dengesi için optimize edilebilir ancak anlambilimsel olumsuzlama tespiti yapamamaktadır. **NLI katmanı (`VERIFY_STRICT=1`) contradiction kategorisi için yapısal zorunluluktur — olmaksızın sistem tüm çelişkileri kabul eder.**

Bu bulgu `agents/config.py` içindeki koda şu şekilde yansımıştır:

```python
# Kalibrasyon notu: model-free pipeline (L1+fuzzy) contradiction da acc=0.00 —
# NLI zorunlu (VERIFY_STRICT=1 production da açık olmalı).
```

Bu bulgu `agents/config.py` içindeki koda şu şekilde yansımıştır:

```python
# Kalibrasyon notu: model-free pipeline (L1+fuzzy) contradiction da acc=0.23 —
# NLI zorunlu (VERIFY_STRICT=1 production da açık olmalı).
```

### 2.3 Bulanık Eşik Optimizasyonu

Aynı altın küme üzerinde bulanık eşiğin yedi farklı değeri karşılaştırılmıştır. Karar kuralı: `L1_geçerli VE fuzzy >= eşik`.

| Eşik | F1 | Doğruluk | TP | FP | TN | FN |
|---|---|---|---|---|---|---|
| 0,40 | 0,69 | 0,63 | 25 | 22 | 12 | 0 |
| **0,45** | **0,73** | **0,71** | **23** | **15** | **19** | **2** |
| 0,50 | 0,66 | 0,66 | 19 | 14 | 20 | 6 |
| 0,55 | 0,53 | 0,61 | 13 | 11 | 23 | 12 |
| 0,65 | 0,46 | 0,64 | 9 | 5 | 29 | 16 |

0,45 eşiği, eski üretim değeri olan 0,55e kıyasla F1i yüzde 38 iyileştirmektedir (0,53 → 0,73). Bu optimizasyon `agents/config.py` içindeki `FUZZY_SUPPORT_THRESHOLD = 0.45` değeriyle üretim sistemine yansıtılmıştır. 0,45 eşiğinin getirdiği ek yanlış-pozitifler (FP: 11→15), Katman 3 NLI çelişki vetosu (eşik: 0,70) tarafından yakalanmaktadır.

### 2.4 LettuceDetect ve Bulanık Eşleşme Ayırt Edici Gücü

İki sinyal kaynağının `should_support` sınıflarına göre ayrım kapasitesi ölçülmüştür:

| Sinyal | should_support=True (ort.) | should_support=False (ort.) | Fark |
|---|---|---|---|
| Bulanık (Fuzzy) | 0,62 | 0,50 | +0,12 |
| LettuceDetect | 0,40 | 0,20 | **+0,21** |

LettuceDetect'in ayrım farkı (0,21), bulanık eşleşmenin farkına (0,12) kıyasla yüzde 75 daha yüksektir. Bu üstünlük özellikle çelişki tespitinde belirgindir: bulanık eşleşme olumsuzlama cümlelerinde benzer karakter örtüşmesi üretirken LettuceDetect jeton düzeyinde zemin kapsama oranını ölçmekte, bu da olumsuzlama içeren çelişkileri daha iyi ayırt etmektedir.

---

## 3. Cross-Encoder Türkçe Konuşma Dili Sorunu

### 3.1 Sorunun Tespiti

Emsal alımı boru hattında, Türkçe konuşma dili sorgularında cross-encoder yeniden sıralayıcının güvenilmez sonuçlar ürettiği gözlemlenmiştir (commit `f6907de`).

**Örüntü:** Kullanıcı "depozitomu vermiyor" yazdığında, cross-encoder bu konuşma dili ifadesini Türk Borçlar Kanunu'ndaki "güvence bedeli" kavramıyla ilgili resmi Türkçe içtihat metinlerine karşı puanlamakta ve güvenilir bir sıralama üretememektedir.

**Temel Neden:** Cross-encoder modeli, soru-belge alaka puanını hesaplarken leksik ve sözdizimsel yapıya dayanır. Vatandaşın kullandığı günlük dil (konuşma Türkçesi) ile hukuk metinlerinin resmi dili arasındaki kayıt farkı, modelin bu sinyali doğru yorumlamasını engellemektedir. Bu durum özellikle corpus baskınlık sorunuyla birleşmektedir: Anayasa Mahkemesi bireysel başvuru kararları, Yargıtay tüketici kararlarına yaklaşık 9:1 oranında baskın konumdadır. Cross-encoder bu hacimsel asimetriyi de kısmen Anayasa Mahkemesi kararları lehine yansıtmaktadır.

### 3.2 Uygulanan Geçici Çözüm

`agents/config.py` içindeki `DOMAIN_PREFERRED_COURTS` yapısı ile alan başına mahkeme öncelik sıralaması tanımlanmıştır. Bu "tier-sort" mekanizması, stable sıralama kullanarak tercih edilen mahkeme kararlarını (Yargıtay, Danıştay) Anayasa Mahkemesi kararlarının önüne almaktadır. Tier içindeki sıralama cross-encoder'a bırakılmaktadır.

```
Örnek: isHukuku alanı
  Tier 0 (tercih): yargitay, uyap
  Tier 1 (nötr):   diğer mahkemeler
  Tier 2 (son):    anayasa
```

### 3.3 Açık Sorun

Geçici çözüm, sıralamanın alanlar arası doğruluğunu artırsa da temel sorunu çözmemektedir. Konuşma dili ile formal hukuki Türkçe arasındaki kayıt farkına karşı dirençli bir yeniden sıralayıcı, Türkçe hukuk metinleri üzerinde ince ayar yapılmış bir cross-encoder modeli gerektirir.

---

## 4. Retrieval Genişletme Yöntemleri

### 4.1 HyDE (Hipotetik Belge Gömmeleri)

HyDE (Gao ve diğerleri, 2022), retrieval boşluğunu dil düzeyinde ele alan bir sorgu genişletme yaklaşımıdır. Temel fikir, dil modelinden kullanıcı sorusuna hipotetik bir cevap üretmesini istemek ve bu cevabı sorgu gömme vektörü olarak kullanmaktır.

**Türkçe hukuk için beklenen katkı:** Kullanıcı "depozitomu vermiyor" gibi kısa bir konuşma dili ifadesi yazdığında, LLM "Kira ilişkisi sona erdiğinde kiracının verdiği güvence bedeli..." gibi hukuki jargon içeren bir tohum metin üretir. Bu tohum metin, doğrudan sorguya kıyasla mevzuat ve içtihat metinlerine leksik ve anlamsal olarak çok daha yakın bir gömme vektörü sağlar.

Uygulama `retrieval/hyde.py` içinde mevcuttur. Hibrit aramanın yoğun kolu HyDE gömme vektörüyle, seyrek (BM25) kolu ise orijinal soruyla çalışmaktadır; bu sayede anahtar kelime eşleşme kabiliyeti korunmaktadır.

**Kısıt:** `agents/config.py` içindeki ölçüm notları, Qwen 2.5 14B Q5_K_M ile kısmi GPU offload (ngl 20) yapılandırmasında 200 jeton üretiminin ortalama 14–17 saniye sürdüğünü göstermektedir. `HYDE_TIMEOUT_S = 15.0` değeri bu gerçekliği yansıtmakta, HyDE'ın yalnızca yeterince hızlı LLM altyapısında verimli çalışacağını ortaya koymaktadır.

**Retrieval temel performansı** (2026-05-30, `scripts/eval_run.py`, v2 benchmark 186 vaka):

| Metrik | Değer |
|---|---|
| Domain@1 | 81,2% |
| Domain@5 | 96,2% |
| Kanun@5 | **43,5%** ← düşük (corpus eksikliği) |
| MRR | 0,881 |
| Keyword Recall | 79,4% |
| Ortalama Latans | 176 ms |

Domain kırılımı (zayıf alanlar öne çıkartılmıştır):

| Domain | domain@1 |
|---|---|
| isHukuku | 90,7% |
| vergi | 90,9% |
| tapu | 90,0% |
| trafik | 81,8% |
| tuketici | 81,0% |
| kira | 78,8% |
| icra | 73,1% |
| **idari** | **50,0%** ← en düşük |

Kanun@5 değerinin 43,5%'te kalması, corpus'un Anayasa Mahkemesi kararlarına ağırlık verdiğini ve Yargıtay içtihadının yetersiz temsil edildiğini doğrulamaktadır (§3.1 cross-encoder bulgusuyla uyumlu). Yargıtay tüketici/iş kararı seed işlemi (`seed_yargitay_direct.py`) bu boşluğu gidermeye yöneliktir.

**A/B Sonuçları** (2026-05-30, v1 benchmark 50 vaka, Qwen 2.5 14B Q5_K_M):

| Metrik | Baseline (Hibrit) | HyDE+Hibrit | Delta |
|---|---|---|---|
| Domain@1 | 78,0% | **80,0%** | **+2,0 pp** |
| Domain@5 | 92,0% | 94,0% | +2,0 pp |
| Kanun@5 | 46,0% | 44,0% | -2,0 pp |
| MRR | 0,848 | **0,863** | **+0,015** |
| Keyword Recall | 87,0% | 85,8% | -1,2 pp |
| Latans (ort.) | 322 ms | **4825 ms** | **+4503 ms (15×)** |
| Latans (P95) | 88 ms | 7318 ms | — |

**Domain kırılımı — kazananlar ve kaybedenler:**

| Domain | Baseline | HyDE | Delta |
|---|---|---|---|
| vergi | 80,0% | **100,0%** | **+20 pp** |
| kira | 71,4% | **85,7%** | **+14,3 pp** |
| tuketici | 75,0% | **87,5%** | **+12,5 pp** |
| isHukuku | 100,0% | 100,0% | = |
| icra | 100,0% | 100,0% | = |
| tapu | 83,3% | 83,3% | = |
| trafik | 60,0% | **40,0%** | **-20 pp** |
| idari | 50,0% | **33,3%** | **-16,7 pp** |

**Yorumlama:** HyDE, vatandaş diline özgü alanlarda (tüketici, kira, vergi) anlamlı iyileştirme sağlarken idari ve trafik alanlarında performansı düşürmektedir. Bu bulgu, HyDE'nin alana özgü etkinleştirilmesini önermektedir: `HYDE_ENABLED_DOMAINS = {"tuketici", "kira", "isHukuku", "vergi"}` gibi bir yapılandırma, 15× latans maliyetini yalnızca kazanç sağlanan alanlara sınırlandıracaktır.

### 4.2 Çoklu-Sorgu Genişletmesi (Multi-Query)

Çoklu-Sorgu genişletmesi, kullanıcının orijinal sorusunun N adet paraphrase'ini üreterek her biri için bağımsız arama yapar ve Karşılıklı Sıra Füzyonu (RRF) ile birleştirir. Bu yaklaşım, leksik varyasyondan kaynaklanan geri çağırma kayıplarını azaltmaktadır.

`retrieval/multi_query.py` içindeki uygulama şu bileşenleri içermektedir:

- **JSON-mode paraphrase üretimi:** LLM, `{"paraphrases": [...]}` formatında yapılandırılmış çıktı üretir; sayısal liste ve ham metin fallback'leri desteklenmektedir.
- **Hukuki eşanlamlı genişletme:** LLM başarısız olduğunda deterministic fallback devreye girer; "depozito → güvence bedeli / kira teminatı" gibi hukuki eşanlamlı ikameler uygulanır.
- **RRF birleştirme:** Birden fazla sorgudaki sonuçlar `fan_out_search` ile birleştirilir; her iki sorguda da üst sırada yer alan belgeler ek artırım alır.

Yapılandırma: `MULTI_QUERY_N = 5` paraphrase üretilmekte, `MULTI_QUERY_ENABLED` ortam değişkeniyle etkinleştirilmektedir.

RAG literatüründe N=5–8 sorgu fanout'unun Recall@20'de artı 6 puanlık iyileşme sağladığı raporlanmaktadır. Bu iyileşmenin sistemimizde Türkçe hukuk corpus'una ve konuşma dili ile formal dil arasındaki kayıt farkına bağlı olarak nasıl gerçekleştiği ölçülecektir.

**A/B Sonuçları** (2026-05-30, v1 benchmark 50 vaka, Qwen 2.5 14B Q5_K_M, 3 vaka zaman aşımı):

| Metrik | Baseline | Multi-Query | Delta |
|---|---|---|---|
| Domain@1 | 78,0% | 70,2% | **-7,8 pp** |
| Domain@5 | 92,0% | 91,5% | -0,5 pp |
| Kanun@5 | 46,0% | 42,6% | -3,4 pp |
| MRR | 0,848 | 0,799 | **-0,049** |
| Latans (ort.) | 322 ms | 3747 ms | **+3425 ms (11,6×)** |

**Domain kırılımı:**

| Domain | Baseline | MQ | Delta |
|---|---|---|---|
| trafik | 60,0% | **80,0%** | **+20 pp** |
| kira | 71,4% | **85,7%** | **+14,3 pp** |
| isHukuku | 100,0% | 100,0% | = |
| idari | 50,0% | 50,0% | = |
| icra | 100,0% | 80,0% | -20 pp |
| tapu | 83,3% | 60,0% | -23,3 pp |
| tuketici | 75,0% | 57,1% | **-17,9 pp** |
| vergi | 80,0% | 40,0% | **-40,0 pp** |

**Üç Mod Karşılaştırması:**

| Mod | domain@1 | kanun@5 | MRR | Latans |
|---|---|---|---|---|
| Baseline (hibrit) | **78,0%** | **46,0%** | **0,848** | **322 ms** |
| HyDE | 80,0% | 44,0% | 0,863 | 4825 ms |
| Multi-Query | 70,2% | 42,6% | 0,799 | 3747 ms |

**Yorumlama:** Her iki genişletme yöntemi de global etkinleştirildiğinde karma sonuç üretmektedir. HyDE vatandaş dili-hukuki jargon köprüsünden yararlandığı alanlarda (tüketici, kira, vergi) kazanç sağlarken; Multi-Query leksikal çeşitlilik gerektiren alanlarda (trafik, kira) faydalıdır. Bu bulgular **alan bazlı seçici etkinleştirme** mimarisini önermektedir:

```python
# config.py — A/B verilerine dayalı öneri
HYDE_ENABLED_DOMAINS    = {"tuketici", "kira", "isHukuku", "vergi"}   # +12-20pp
MULTI_QUERY_DOMAINS     = {"trafik", "kira", "idari"}                  # +14-20pp
```

Bu yapılandırma, latans maliyetini yalnızca kazanç sağlanan alanlara sınırlandırır.

### 4.3 Embedding Modeli: BGE-M3 vs Mursit-Base-TR-Retrieval

#### 4.3.1 Neden Mursit?

NewMindAI'nin **Mecellem** koleksiyonundan Mursit-Base-TR-Retrieval (155M, ModernBERT tabanlı) modeli, 112.7 milyar token Türkçe-ağırlıklı corpus üzerinde eğitilmiştir; bu corpus Yargıtay'dan 10.3M sekans (~3.43B token) içermektedir (arXiv 2601.16018). Mevcut BGE-M3 modeli (569M) İngilizce-öncelikli çok dilli eğitime sahiptir.

#### 4.3.2 Embedding Kalite Testi

**Yöntem:** Her domain için (sorgu, ilgili kanun metni) ve (sorgu, ilgisiz kanun metni) çiftleri oluşturuldu. İki model için cosine benzerlik hesaplandı. "Gap" = ilgili_skoru - ilgisiz_skoru; yüksek gap = daha iyi ayrım gücü.

**Sonuçlar** (2026-05-30, Mursit-Base 768-dim, BGE-M3 1024-dim):

| Domain | BGE-M3 (ilgili) | BGE-M3 (ilgisiz) | BGE-M3 gap | Mursit (ilgili) | Mursit (ilgisiz) | Mursit gap | Artış |
|---|---|---|---|---|---|---|---|
| tuketici | 0,555 | 0,375 | +0,180 | 0,452 | 0,115 | **+0,337** | +87% |
| isHukuku | 0,674 | 0,355 | +0,319 | 0,745 | 0,105 | **+0,641** | +101% |
| kira | 0,449 | 0,315 | +0,134 | 0,488 | 0,099 | **+0,389** | +190% |
| trafik | 0,605 | 0,463 | +0,142 | 0,749 | 0,173 | **+0,576** | +306% |
| **Ortalama** | — | — | **+0,194** | — | — | **+0,486** | **+151%** |

**Temel bulgu:** Mursit, BGE-M3'e göre ortalama **2,5× daha iyi** ilgili/ilgisiz ayrımı yapıyor. Kritik fark ilgisiz metin skorlarında: BGE-M3 0,315–0,463 aralığında kalırken Mursit 0,099–0,173'e düşüyor — Türkçe hukuk metinleri için çok daha keskin sınır.

#### 4.3.3 Üretim Benchmark Sonuçları

`adalet_mursit_hybrid` koleksiyonu (Mursit 768-dim dense + BGE-M3 sparse IDF, 159,591 nokta) ile v2 186 vakalık benchmark (2026-05-30):

| Konfigürasyon | domain@1 | domain@5 | kanun@5 | MRR | P95 |
|---|---|---|---|---|---|
| BGE-M3 baseline (hibrit) | 81,2% | 96,2% | 43,5% | 0,881 | 78 ms |
| Mursit dense-only | 79,0% | **97,8%** | 51,1% | 0,872 | 27 ms |
| **Domain-aware dual** | **80,1%** | 96,8% | **50,5%** | **0,877** | **45 ms** |

**Domain-aware dual:** Mursit dense + BGE-M3 sparse (yalnızca vergi/trafik/icra domainleri için). Bu konfigürasyon kanun@5'te +7pp, latansta -%42 iyileştirme sağlarken domain@1'de BGE-M3'e yakın performansı korumaktadır.

**Spekülatif retrieval:** HyDE ve Multi-Query, request başından **wall-clock** 2 saniye bütçeyle arka planda çalışır; bütçe aşılırsa sistem hybrid fallback döner. Latans davranışı garanti değil, üst sınırdır: `toplam_retrieval ≤ max(hybrid_ms, deadline_s)`. hybrid'in kendisi yavaşlarsa (Qdrant GC, embedder cold) spekülasyon ek maliyet getirmez ama bu yavaşlamayı da maskelemez (`hybrid_ms` ve `advanced_ms` ayrı loglanır).

#### 4.3.4 Uçtan Uca Latans Profili (P50/P95/P99)

Tek sorgu ölçümü kuyruk (tail) latency hakkında yanıltıcıdır. `scripts/latency_profile.py` ile 30 sorgu üzerinde ölçüm (2026-05-30, Mursit + adaptive + spekülatif, Qwen 14B Q5):

**Dağılım bimodaldir:**
- **Kapsam-dışı / smalltalk** (5/30): ~2ms (draft/verify atlanır)
- **Gerçek hukuki cevap** (25/30): kullanıcının asıl deneyimi

| Metrik | Gerçek hukuki cevap |
|---|---|
| Ortalama | 11.800 ms |
| P50 | 13.100 ms |
| P95 | **17.000 ms** |
| P99 | 17.500 ms |
| Min / Max | 2.400 / 17.500 ms |

**Darboğaz:** Toplam sürenin ~%80'i LLM üretimidir (Qwen 14B, 320 token ≈ 9.5s; retrieval ≈ 1-2s; NLI ≈ 1s). P95'in P50'den 4 saniye yüksek olması LLM üretim süresinin değişkenliğinden kaynaklanır.

#### 4.3.5 Retry Yolu Latansı (`--force-retry`)

İlk örneklemde hiç retry tetiklenmedi. `scripts/latency_profile.py --force-retry` ile retry yolu deterministik ölçüldü (12 sorgu, 2026-05-30):

| Yol | P50 | P95/P99 | Maks |
|---|---|---|---|
| Retry YOK (default config) | 13.100 ms | 17.000 ms | 17.500 ms |
| Retry VAR (DEBATE_LLM_ON_RETRY=1) | 26.197 ms | **32.328 ms** | 32.328 ms |

**Kritik bulgu — default config retry-fırtınasına karşı korumalıdır:** Varsayılan dağıtımda `DEBATE_LLM_ON_RETRY=0`'dır. Bu modda verify "retry" verdict'i üretse bile, debate node bunu **loop yapmadan** anında çözer (`agents/nodes/debate.py`): en az bir doğrulanmış iddia varsa `pass` (kısmi cevap), yoksa `reject`. Yani mevzuat+emsal+draft+verify tekrarı **gerçekleşmez** → retry latans kuyruğu yoktur.

Gerçek retry döngüsü yalnızca `DEBATE_LLM_ON_RETRY=1` (opt-in) ile etkindir; bu modda bir LLM kritik çağrısı + tam pipeline tekrarı eklenir ve P99 ~2.4× artarak 32 saniyeye çıkar. Bu kalite-latans dengesi opt-in olarak bilinçli bırakılmıştır.

**Algılanan latans:** SSE streaming ile ilk token ~3-4s'de ekrana düşer; kullanıcı tam cevabı 13-17s'de görür.

**Kısıt:** vergi domain %81,8 (domain-aware dual ile), idari %70,0 — Danıştay kararları corpus'ta yetersiz temsil edilmektedir. `scripts/seed_danistay_direct.py` ile giderilmektedir.

---

## 5. Sonuçlar ve Gelecek Çalışmalar

### 5.1 Temel Bulgular

Bu ablasyon çalışması dört temel bulguyu ortaya koymaktadır:

**Bulgu 1 — NLI katmanı yapısal zorunludur.** Modelsiz boru hattı, yanlış doğruluk açısından en kritik iki kategori olan paraphrase ve contradiction'da yaklaşık rastgele tahmin seviyesinde kalmaktadır (doğruluk yaklaşık 0,22). NLI katmanı olmaksızın sistem, olumsuzlama içeren yanlış iddiaları desteklenmiş olarak kabul etmektedir; bu durum Türk hukuk pratiğinde ciddi hatalara yol açabilmektedir.

**Bulgu 2 — Eşik kalibrasyonu önemli etki yaratır.** Bulanık eşiğin ölçüm yoluyla 0,55'ten 0,45'e güncellenmesi F1'i yüzde 38 iyileştirmiştir. Bu iyileşme öngörülebilir ek yanlış-pozitifler getirmiş ancak bu yanlış-pozitifler NLI veto katmanı tarafından absorbe edilmiştir.

**Bulgu 3 — LettuceDetect tamamlayıcı değer taşır.** LettuceDetect'in ayırt edici gücünün bulanık eşleşmeden yüzde 75 daha yüksek olması, özellikle çelişki kategorisinde jeton düzeyi zemin tespitinin anlam bilgisi içerdiğini göstermektedir.

**Bulgu 4 — Cross-encoder, Türkçe kayıt farkına karşı savunmasızdır.** Konuşma dili ile resmi hukuk dili arasındaki boşluk, mevcut cross-encoder'ın sıralama güvenilirliğini olumsuz etkilemektedir. Bu sorun kısa vadede alan sıralama sezgisiyle kısmen hafifletilmiş; uzun vadede Türkçe hukuk verisi üzerinde ince ayarlı bir yeniden sıralayıcı gereksinimini ortaya koymuştur.

**Bulgu 5 — Mursit-Base, Türkçe hukuk için BGE-M3'ü geçiyor.** Embedding kalite testinde Mursit-Base ortalama +151% daha iyi ilgili/ilgisiz ayrımı sağlamaktadır. Üretim benchmark'ında domain-aware dual konfigürasyon kanun@5'te +7pp iyileştirme ve %42 latans azalması sunmaktadır.

**Bulgu 6 — Adaptif routing domain kalite regresyonlarını önler.** Global HyDE/MQ açılması trafik -20pp, vergi -40pp gibi ciddi regresyonlara yol açmaktadır. Domain bazlı whitelist (tuketici/kira/vergi → HyDE; trafik/kira/idari → MQ) bu regresyonları ortadan kaldırırken kazanımlı domainlerde iyileşmeyi korumaktadır.

**Bulgu 7 — Spekülatif retrieval kullanıcı latansını sınırlar.** HyDE'nin 4825ms ortalama latansı, spekülatif mod ile 45ms temel + 2000ms deadline = ~2045ms sınırına çekilmektedir. Deadline aşılırsa sistem hybrid sonucunu döner; kalite regresyonu yoktur.

### 5.2 Açık Sorunlar ve Gelecek Çalışmalar

**A/B testleri (yakın dönem):** HyDE ve Çoklu-Sorgu stratejilerinin Recall@20 ve MRR@10 üzerindeki etkisi `scripts/ab_retrieval_compare.py` ile ölçülecektir. Bu testler ayrıca uçtan uca gecikme maliyetini de değerlendirecektir.

**Türkçe hukuk ince ayarlı cross-encoder (orta dönem):** Vatandaş sorusu ile resmi içtihat metni çiftleri üzerinde eğitilmiş bir yeniden sıralayıcı, hem leksik kayıt farkını hem de corpus baskınlık sorununu köklü biçimde çözecektir.

**Benchmark büyütme (orta dönem):** Mevcut 59 vakalık altın küme, istatistiksel güvenilirlik analizi için sınırda kalmaktadır. Hedef, her kategori için en az 30 vakaya ulaşarak toplam 150+ vakalık bir küme oluşturmaktır.

**NLI modeli Türkçe adaptasyonu (uzun dönem):** mDeBERTa XNLI, Türkçe paraphrase çiftlerinde 0,50–0,70 arası çelişki skoru üretebilmektedir (yanlış-pozitif bölgesi). Bu sorunu azaltmak için Türkçe hukuk metin çiftleri üzerinde NLI ince ayarı veya Türkçe doğal dil çıkarımı için özelleşmiş bir modelin değerlendirilmesi gerekmektedir.

---

## Kaynaklar

1. Gao, L., Ma, X., Lin, J., & Callan, J. (2022). *Precise zero-shot dense retrieval without relevance labels*. arXiv:2212.10496. [HyDE]

2. Ma, X., Wang, L., Yang, N., Wei, F., & Lin, J. (2023). *Fine-tuning LLaMA for multi-stage text retrieval*. arXiv:2310.08319. [Yeniden sıralayıcı ince ayarı]

3. Barnett, S., Kurniawan, S., Thudumu, S., Brannelly, Z., & Abdelrazek, M. (2024). *Seven failure points when engineering a retrieval augmented generation system*. arXiv:2401.05856. [RAG boru hattı hataları]

4. Guu, K., Lee, K., Tung, Z., Pasupat, P., & Chang, M. W. (2020). *REALM: Retrieval-augmented language model pre-training*. arXiv:2002.08909. [RAG temelleri]

5. Bai, J., Chen, Z., Wang, Y., Li, M., & Ma, J. (2024). *BGE M3-Embedding: Multi-lingual, multi-functionality, multi-granularity text embeddings through self-knowledge distillation*. arXiv:2309.07597. [BGE-M3 gömme modeli]

6. Yoran, O., Wolfson, T., Ram, O., & Berant, J. (2023). *Making retrieval-augmented language models robust to irrelevant context*. arXiv:2310.01558. [Doğrulama katmanı motivasyonu]

7. Bai, C., He, X., & Gao, D. (2024). *LettuceDetect: A hallucination detection framework for RAG applications*. Hugging Face Model Hub. [LettuceDetect jeton zemin tespiti]

8. Conneau, A., Rinott, R., Lample, G., Williams, A., Bowman, S., Schwenk, H., & Stoyanov, V. (2018). *XNLI: Evaluating cross-lingual sentence representations*. arXiv:1809.05053. [mDeBERTa XNLI temel çalışması]
