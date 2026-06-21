# ADALET-AGENT — Yarışma & Hibe Başvuru Özeti

> [!IMPORTANT]
> Bu belge yarışma/hibe anlatısıdır. Güncel test sayıları, model/korpus notları,
> auth kapsamı ve doğrulama sınırları için [`docs/CURRENT_STATUS.md`](CURRENT_STATUS.md)
> esas alınır.

> **Amaç:** Bu doküman, TÜBİTAK 2209-A, Teknofest (Türkçe NLP / İnsanlık Yararına
> Teknoloji / Yazılım) ve benzeri başvurularda doğrudan kullanılmak üzere
> hazırlanmıştır. Buradaki teknik iddiaların tamamı kod tabanında karşılığı olan,
> test edilmiş ve doğrulanabilir çalışmalardır. Açık kaynak olduğundan jüri
> tarafından bağımsız incelenebilir.

---

## 1. Tek Cümlelik Tanım

**ADALET, avukat tutamayan vatandaşlara; gerçek Yargıtay kararları ve mevzuatla
*doğrulanmış*, *uydurmayan* (sıfır-halüsinasyon hedefli), çok modlu (yazılı + sesli
+ belge fotoğrafı) ve şeffaf bir Türkçe hukuk yapay zekâ asistanıdır.**

---

## 2. Çözülen Problem

Mevcut genel amaçlı yapay zekâ araçları (ChatGPT, Gemini) hukukta **tehlikeli**dir:
var olmayan kanun maddeleri ve sahte mahkeme kararları "uydururlar"
(*halüsinasyon*). Bir vatandaş bu uydurma bilgiyle hareket ederse hak kaybına
uğrayabilir. Türkiye'de hukuki danışmanlık maliyeti, dezavantajlı kesimler için
adalete erişimin önünde somut bir engeldir.

**ADALET'in cevabı:** yasal iddiaların orijinal kaynağıyla (mevzuat.gov.tr,
Yargıtay) karşılaştırıldığı; sahte kaynakların, kaynakla çelişen iddiaların ve
veto edilen içeriklerin nihai yanıttan temizlendiği **çok-ajanlı** bir mimari.

---

## 3. Özgün Bilimsel/Teknik Katkılar

| # | Katkı | Neden özgün |
|---|-------|-------------|
| 1 | **İddia-doğrulamalı çoklu-ajan mimarisi** | Cevap üretmeden önce iddialar kaynaklarla eşleştirilir; sahte/çelişen iddialar temizlenir, riskli durumda güvenli hata veya yeniden deneme yolu kullanılır. |
| 2 | **Türkçe hukuk için citation verification** | NLI (doğal dil çıkarımı) tabanlı doğrulama katmanı + RARR; iddia ↔ kaynak metin eşleşmesi ölçülür. |
| 3 | **Türkçe konuşma-dili → hukuk dili köprüsü** | Vatandaşın günlük diliyle sorduğu soruyu mevzuat/içtihat terminolojisine eşleyen retrieval (BM25 + dense + reranker). |
| 4 | **Dürüst kapsam sınırı** | Sistem yetkin olmadığı alanları (ceza, aile hukuku) **bilerek reddeder** — "ne yapamadığını bilen" asistan. |
| 5 | **Açıklanabilirlik (explainability)** | Her cevapta hangi ajanın ne dediği, güven skoru ve doğrulanan iddia sayısı kullanıcıya gösterilir. |
| 6 | **Dava sonucu tahmini** | Geçmiş Yargıtay kararlarına dayalı istatistiksel tahmin (ML), zorunlu sorumluluk reddiyle. |

---

## 4. Sistem Mimarisi (kodda mevcut)

**Çok-ajanlı orkestrasyon — LangGraph (state graph):**
triaj → mevzuat → emsal → taslak → **doğrulama** → tartışma (debate) → tahmin →
sonuç. Ek olarak **CRAG**, **Self-RAG**, eligibility ve clarifier gibi ileri düğümler.

**İleri RAG yığını:** hibrit arama (BM25 + dense), HyDE, multi-query, **RAPTOR**
(hiyerarşik özet), **graph-RAG**, spekülatif retrieval, adaptive router, cross-encoder
reranker, Türkçe metin normalizasyonu, citation çıkarımı.

**Doğrulama katmanı (verifier):** NLI, RARR, lettuce + önbellek.

> **Dürüstlük notu (jüri için):** Üretim default hattı **8 ajan + V2 policy**'dir:
> triaj → (mevzuat ∥ emsal) → draft → verify (4-katman) → debate → finalize, +
> clarifier/policy. **RAPTOR, GraphRAG, CRAG, Self-RAG, eligibility ve dava-tahmini
> opt-in/deneysel modüllerdir** (ENV-gated, üretim default'unda KAPALI; bazıları
> ölçüm bekliyor). Kod tabanında mevcut ve test edilirler ama "kanıtlanmış üretim
> sonucu" olarak sunulmazlar — kapsam sınırları ölçülmüş sonuçlardan ayrı tutulur.

**Çok modlu (multimodal):** OCR (belge fotoğrafı → metin, PII otomatik maskeli),
STT (sesli giriş), TTS (sesli okuma).

**Tahmin (predictive):** eğitim + çıkarım + kalibrasyon pipeline'ı.

**Veri katmanı:** Postgres (10 tablo) + Redis + dosya fallback; Alembic migration'lar.

**Teknoloji:** Python 3.11 / FastAPI / LangGraph (backend) · Vite + React (web) ·
Flutter (mobil, planlı) · yerel açık-ağırlık LLM (Qwen) · Qdrant vektör DB.

> Tüm yasal veri kaynakları **kamuya açıktır** (Mevzuat Bilgi Sistemi, Yargıtay,
> Resmî Gazete, Danıştay) — KVKK/etik kurul açısından engel yoktur.

---

## 5. Son Geliştirme Döneminde Tamamlanan Somut İşler (doğrulanmış)

Aşağıdaki üç özellik bu dönemde **uçtan uca geliştirilmiş, test edilmiş ve
çalışır** durumdadır (frontend + backend + veritabanı):

### 5.1 Ürün-seviyesi kullanıcı deneyimi
- **ADALET'e özgü hesap/profil menüsü:** 8-ajan şeffaflık paneli, 8 hukuk alanı +
  kapsam-dışı dürüstlüğü, kaynak şeffaflığı, **erişilebilirlik tercihleri**
  (yazı boyutu, hareketi azalt, yüksek kontrast — Üye-2 "Erişilebilir Hukuk"
  tezi ile uyumlu).

### 5.2 Kalıcı sohbet geçmişi + bilgi yönetimi
- Kayıtlı kullanıcının **sohbet geçmişi** kalıcı saklanır; geçmişte arama,
  **kaynak kütüphanesi** (tüm sohbetlerde atıf yapılan kanun/karar birikimi) ve
  **belge yönetimi** ("Dosyalarım").

### 5.3 Kimlik doğrulama
- Güncel web ürününde Supabase tabanlı kayıt/giriş zorunludur; sohbet geçmişi,
  kaynak kütüphanesi ve dosya yönetimi oturum açmış kullanıcıya bağlıdır.
  Misafir/localStorage-only sohbet modu güncel ürün davranışı değildir.

> Bu üç iş için yapılan **çok-ajanlı kod incelemesi** (güvenlik + kalite ajanları)
> sonucunda **kritik açık tespit edilmemiş**, yüksek öncelikli bulgular giderilmiştir.

---

## 6. Teknik Olgunluk & Kalite Güvencesi

Bir öğrenci projesi için sıra dışı bir mühendislik disiplini:

- **2026-06-21 doğrulaması:** backend hızlı pakette 1546 test, frontend birim/entegrasyon paketinde 262 test ve Playwright e2e paketinde 11 test geçti. Ayrıntı ve hariç tutulan entegrasyon alanları için `docs/CURRENT_STATUS.md`.
- **Sürekli entegrasyon (CI):** ruff (lint), bandit (güvenlik), mypy (tip
  denetimi) — tümü yeşil.
- **Çok-ajanlı kod & güvenlik incelemesi** her özellikte (OWASP perspektifi).
- **Değerlendirme altyapısı:** ablation çalışması (yapıldı, `ablation_study.md`),
  186-vakalık Türkçe hukuk benchmark'ı (500 hedef), Wilson %95 CI'li scorecard,
  Ragas faithfulness altyapısı (toplu koşum bekliyor), Langfuse izleme.
- **Açık kaynak (MIT)** — şeffaflık iddiası *kanıtlanabilir*.

---

## 7. Etik, Gizlilik, Erişilebilirlik

- **KVKK uyumu (arka plan hijyeni):** kullanıcı kimliği veritabanında **ham
  saklanmaz** (geri-dönüşümsüz parmak izi); belge PII'si (TCKN/telefon/IBAN)
  **otomatik maskelenir**; yapay zekâ modelleri **yerel** çalışır (production'da
  bulut LLM çağrısı yok); veri **Türkiye sınırları içinde** kalır.
- **Hukuki sorumluluk:** her yanıtta zorunlu sorumluluk reddi; sistem vekâlet
  almaz, mahkemede temsil etmez (Avukatlık Kanunu'na uyum).
- **Erişilebilirlik:** klavye navigasyonu, ekran-okuyucu desteği, hareket-azaltma,
  yazı boyutu — dezavantajlı kullanıcıyı merkeze alır.

---

## 8. Yarışma Kategorilerine Uygunluk

| Yarışma / Kategori | Uyum gerekçesi |
|--------------------|----------------|
| **TÜBİTAK 2209-A** | Özgün araştırma sorusu (Türkçe hukuk için doğrulamalı RAG + dava tahmini); yöntem, ölçüm ve yaygın etki net. |
| **Teknofest — Türkçe NLP** | Çekirdek katkı Türkçe doğal dil işleme: konuşma-dili→hukuk-dili retrieval, NLI doğrulama, Türkçe metin normalizasyonu. |
| **Teknofest — İnsanlık Yararına Teknoloji** | Adalete erişimde eşitsizliği azaltır; dezavantajlı vatandaşı hedefler; erişilebilirlik birinci sınıf. |
| **Teknofest — Yazılım & Dijital** | Açık kaynak, yüksek mühendislik olgunluğu (2026-06-21 hızlı doğrulamada 1546 backend + 262 frontend + 11 e2e test), modüler mimari. |
| **Imagine Cup** | Toplumsal etki + ileri yapay zekâ; Azure entegrasyonuna uygun mimari. |

---

## 9. Yaygın Etki & Ölçülebilir Hedefler

- **Sosyal etki:** avukat maliyetini karşılayamayan vatandaşlar için ilk-basamak
  hukuki bilgilendirme; 8 sivil hukuk alanı (tüketici, iş, kira, icra, trafik,
  vergi, tapu, idari).
- **Akademik çıktı:** Türkçe hukuk RAG benchmark'ı + dava sonucu tahmini üzerine
  makale (TIDE-TR / SIU hedefi); 4 lisans bitirme tezi.
- **Açık bilim:** benchmark, değerlendirme kodu ve sistem MIT lisansıyla
  paylaşılarak Türkçe hukuk-NLP ekosistemine katkı.

---

## 10. Tek Paragraf Özet (başvuru girişi için kullanılabilir)

> ADALET, Türkiye'de avukata erişemeyen vatandaşlar için geliştirilen, açık kaynaklı
> (MIT) bir Türkçe hukuk yapay zekâ asistanıdır. Genel amaçlı dil modellerinin
> hukukta yarattığı "yasa uydurma" (halüsinasyon) tehlikesine; yasal iddiaları
> Yargıtay ve mevzuat gibi resmî kaynaklarla karşılaştıran, sahte veya çelişen
> içeriği temizleyen **iddia-doğrulamalı çoklu-ajan** mimarisiyle çözüm getirir.
> Sistem; ileri RAG
> (HyDE, RAPTOR, hibrit arama, NLI doğrulama), çok modlu giriş (belge OCR + sesli),
> dava sonucu tahmini ve açıklanabilirlik (her ajanın katkısı + güven skoru)
> sunar. KVKK-uyumlu (yerel model, PII maskeleme, anonim parmak izi), erişilebilir
> ve 1546 backend hızlı test + 262 frontend testi + 11 e2e testlik son doğrulama
> matrisiyle CI güvencesi altında geliştirilmiştir.

---

*Bu belge başvuru anlatısıdır; güncel doğrulama için önce `docs/CURRENT_STATUS.md`
okunmalıdır. Teknik detaylar için: `docs/architecture.md`, `docs/ablation_study.md`,
`docs/benchmark/`, `docs/theses/`.*
