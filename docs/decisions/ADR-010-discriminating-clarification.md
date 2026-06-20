# ADR-010 — Ayırt edici (discriminator) çok-tur netleştirme

**Durum:** Accepted (uygulandı, commit bekliyor)
**Tarih:** 2026-06-20

## Bağlam
Kullanıcı geri-bildirimi: "kiracımı çıkaramıyorum" gibi **eksik-bilgili** sorularda
sistem yüzeysel cevap veriyor; oysa doğru hukuki sonuç asıl belirleyici parametreye
(tahliye **sebebi**) göre tümden değişir. Hukukta cevap bir sürü parametreye bağlı;
kullanıcıdan tam bilgi almadan verilen sonuç yanlış olabilir.

Deep-research (108 ajan, arXiv) **CLAM 3-aşamalı seçici netleştirme** desenini doğruladı
(2212.07769 / 2311.09469): *belirsizliği tespit et → doğru netleştirici soruyu üret →
cevapla*. Karar **kalibre edilebilir bir kapı** olmalı — "her zaman sor" da "hiç sorma"
da yanlış; yalnız eksik parametre cevabı **değiştiriyorsa** sor (seçici netleştirme
doğruluğu ~20pp↑; aşırı-soru zararlı — A2J Author / Amazon Science).

Mevcut sistem zaten clarifier + merkezî `policy.decide_path()` içeriyordu ama sığdı:
domain başına SABİT jenerik soru bankası, **tek tur**, sayı-eşiği, dallanma yok.

## Karar
Domain başına **veri-odaklı ayırt edici senaryo** (`agents/clarify_slots.py`):
`_Scenario(detect, reason_present, reason_fact_key, questions, followup, options)`.
3 aşama:
1. **Tespit** — `detect` (örn. `is_landlord_eviction` = kiracı + tahliye-fiili +
   kullanıcı-kiracı-değil; dar kapsam, kalibrasyon korunur).
2. **Üret** — sebep belli değilse round-1 sebep sorusu + **tıklanabilir cevap-şıkları**
   (`options`); sebep belliyse round-2 **sebebe-özel** follow-up (`followup`).
3. **Cevapla** — sebep + ayrıntı toplandığında tam-tabloya göre cevap.

Sert sınır: **2 tur** (`MAX_DISCRIMINATOR_ROUNDS`), çapraz-tur `_clarify_chain_len`
(chat_history'de sondan geriye kesintisiz `CLARIFY_MARKER` zinciri) → sonsuz döngü
imkânsız. Discriminator gate, "nasıl/ne yapabilirim" gibi GENEL kalıba rağmen önce
ayırt edici parametreyi sorar (yalnız situational discriminator senaryolarında).

**Tek-kaynak (DRY):** `reason_present` → `reason_category`'ye delege; chip ile
serbest-metin AYNI tanımayı kullanır (kullanıcı şıkka tıklasa da kendi cümlesiyle
yazsa da aynı round-2 tetiklenir). Şıklar opsiyonel; yazı kutusu hep açık.

**Sıfır halüsinasyon:** sorular/şıklar olgu-toplar, madde/karar numarası İÇERMEZ;
hukuki iddiayı draft/mevzuat üretir. Sebep adları (ihtiyaç, devamsızlık…) hukuki iddia
değil, durumu sınıflayan ŞIKLARDIR.

Uygulanan domainler (tek ayırt edici eksenin cevabı belirlediği): **kira** (tahliye
sebebi: ihtiyaç/temerrüt/taahhüt/yeniden-inşa/10-yıl/yeni-malik), **iş** (fesih sebebi:
haklı/geçerli/ekonomik), **icra** (duruş: itiraz/kabul/alacaklı; SIKI olay-tabanlı
tespit — genel "nasıl açılır" tetiklemez). Kalan 5 domain tek-eksenli reason-branchy
DEĞİL → prensiple zorlanmadı (over-clarification riski).

## Yeni domain nasıl eklenir
`clarify_slots.py`'de: (1) `detect`/`reason_category`/`reason_present` saf fonksiyonları,
(2) round-1 `_SLOTS` + `_clarify_questions`, (3) round-2 `_FOLLOWUPS` + `_followup`,
(4) tıklanabilir `_OPTIONS` (her etiket sebep-anahtarı taşımalı ama round-2 "zaten-cevaplı"
işaretini İÇERMEMELİ), (5) `_SCENARIOS["domain"] = _Scenario(...)`. policy/clarifier/API
otomatik kullanır. ÖNCE kalibrasyon testi yaz (genel how-to → answer kalmalı).

## Sonuç
backend 822 + frontend 228 test yeşil, 0 regresyon. Code-review (ADR yazımında):
0 CRITICAL, 1 HIGH (ClarifyCard `data.options` guard — düzeltildi), kalan bilinçli
tradeoff/zararsız. API: `clarifying_questions` + `clarify_options` yapısal alanları;
frontend kırılgan regex sezgisi yerine `response_intent`/yapısal alanla tespit eder.

## Alternatifler
- **LLM-tabanlı ambiguity detector**: stokastik, deterministik policy'ye uymaz; CLAM
  prompt-tabanlı kapıyı önerse de bizde sıfır-LLM-policy ilkesi var (test edilebilir).
- **Serbest-metin LLM clarifier**: halüsinasyon yüzeyi + öngörülemez; sabit/veri-odaklı
  şema güvenli (madde numarası sızmaz).
- **Tüm 8 domaine zorla discriminator**: over-clarification regresyonu (tekrarlayan
  ağrı); yalnız reason-branchy domainlere uygulandı.

## İlgili
- [agents/clarify_slots.py](../../backend/agents/clarify_slots.py)
- [agents/policy.py](../../backend/agents/policy.py) — `decide_path`, `_clarify_chain_len`
- [agents/nodes/clarifier.py](../../backend/agents/nodes/clarifier.py)
- [api/schemas.py](../../backend/api/schemas.py) — `clarifying_questions`, `clarify_options`
- [frontend/src/components/cards.jsx](../../frontend/src/components/cards.jsx) — `ClarifyCard`
- [ADR-002](ADR-002-llm-mode-split.md) — sıfır-LLM deterministik policy ilkesi
