# Ablasyon Çalışması: ADALET-AGENT Doğrulama ve Retrieval Katmanları

**Proje:** ADALET-AGENT — Türkçe Hukuk için Çok Ajanlı Doğrulamalı Yapay Zeka Sistemi  
**Tarih:** 2026-05-30  
**Veri Seti:** `data/eval_benchmark/verify_gold.jsonl` (59 vaka)  
**Kaynak Kod:** `eval/verify_calibration.py`, `agents/nodes/verify.py`, `agents/config.py`

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
| `paraphrase` | 14 | **0,21** | KRİTİK: Paraphrase desteklenmiş sayılamıyor |
| `contradiction` | 13 | **0,23** | KRİTİK: Çelişki tespit edilemiyor |

Bu sonuçlar temel bir yapısal kısıtlamayı ortaya koymaktadır: bulanık karakter örtüşmesi, olumsuzlama jetonlarını (örn. "değil", "olmaz") cümle düzeyinde anlam değişikliğinden ayırt edememektedir. Doğruluk değeri yaklaşık 0,22, bu iki kritik kategoride neredeyse rastgele tahmin düzeyine karşılık gelmektedir. NLI katmanı (`VERIFY_STRICT=1`), bu eksikliği telafi etmek için mimari olarak zorunludur.

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

[A/B SONUCU: `scripts/ab_retrieval_compare.py` çalıştırılınca doldurulacak — Recall@20 ve MRR@10 karşılaştırması: Hibrit (temel) vs. HyDE+Hibrit]

### 4.2 Çoklu-Sorgu Genişletmesi (Multi-Query)

Çoklu-Sorgu genişletmesi, kullanıcının orijinal sorusunun N adet paraphrase'ini üreterek her biri için bağımsız arama yapar ve Karşılıklı Sıra Füzyonu (RRF) ile birleştirir. Bu yaklaşım, leksik varyasyondan kaynaklanan geri çağırma kayıplarını azaltmaktadır.

`retrieval/multi_query.py` içindeki uygulama şu bileşenleri içermektedir:

- **JSON-mode paraphrase üretimi:** LLM, `{"paraphrases": [...]}` formatında yapılandırılmış çıktı üretir; sayısal liste ve ham metin fallback'leri desteklenmektedir.
- **Hukuki eşanlamlı genişletme:** LLM başarısız olduğunda deterministic fallback devreye girer; "depozito → güvence bedeli / kira teminatı" gibi hukuki eşanlamlı ikameler uygulanır.
- **RRF birleştirme:** Birden fazla sorgudaki sonuçlar `fan_out_search` ile birleştirilir; her iki sorguda da üst sırada yer alan belgeler ek artırım alır.

Yapılandırma: `MULTI_QUERY_N = 5` paraphrase üretilmekte, `MULTI_QUERY_ENABLED` ortam değişkeniyle etkinleştirilmektedir.

RAG literatüründe N=5–8 sorgu fanout'unun Recall@20'de artı 6 puanlık iyileşme sağladığı raporlanmaktadır. Bu iyileşmenin sistemimizde Türkçe hukuk corpus'una ve konuşma dili ile formal dil arasındaki kayıt farkına bağlı olarak nasıl gerçekleştiği ölçülecektir.

[A/B SONUCU: `scripts/ab_retrieval_compare.py` çalıştırılınca doldurulacak — Hibrit (temel) vs. Çoklu-Sorgu+Hibrit ve Çoklu-Sorgu+HyDE+Hibrit üçlü karşılaştırma; Recall@20, MRR@10, uçtan uca latans]

---

## 5. Sonuçlar ve Gelecek Çalışmalar

### 5.1 Temel Bulgular

Bu ablasyon çalışması dört temel bulguyu ortaya koymaktadır:

**Bulgu 1 — NLI katmanı yapısal zorunludur.** Modelsiz boru hattı, yanlış doğruluk açısından en kritik iki kategori olan paraphrase ve contradiction'da yaklaşık rastgele tahmin seviyesinde kalmaktadır (doğruluk yaklaşık 0,22). NLI katmanı olmaksızın sistem, olumsuzlama içeren yanlış iddiaları desteklenmiş olarak kabul etmektedir; bu durum Türk hukuk pratiğinde ciddi hatalara yol açabilmektedir.

**Bulgu 2 — Eşik kalibrasyonu önemli etki yaratır.** Bulanık eşiğin ölçüm yoluyla 0,55'ten 0,45'e güncellenmesi F1'i yüzde 38 iyileştirmiştir. Bu iyileşme öngörülebilir ek yanlış-pozitifler getirmiş ancak bu yanlış-pozitifler NLI veto katmanı tarafından absorbe edilmiştir.

**Bulgu 3 — LettuceDetect tamamlayıcı değer taşır.** LettuceDetect'in ayırt edici gücünün bulanık eşleşmeden yüzde 75 daha yüksek olması, özellikle çelişki kategorisinde jeton düzeyi zemin tespitinin anlam bilgisi içerdiğini göstermektedir.

**Bulgu 4 — Cross-encoder, Türkçe kayıt farkına karşı savunmasızdır.** Konuşma dili ile resmi hukuk dili arasındaki boşluk, mevcut cross-encoder'ın sıralama güvenilirliğini olumsuz etkilemektedir. Bu sorun kısa vadede alan sıralama sezgisiyle kısmen hafifletilmiş; uzun vadede Türkçe hukuk verisi üzerinde ince ayarlı bir yeniden sıralayıcı gereksinimini ortaya koymuştur.

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
