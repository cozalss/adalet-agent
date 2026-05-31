# `/sor` Ekranı — UI/UX Tasarım Spesifikasyonu

> Kaynak: 104-ajanlı deep-research (24/25 iddia adversarial doğrulandı), 2026-05-31.
> Bu doküman bir tasarımcının veya Claude Design'ın **doğrudan uygulayabileceği** detaydadır.
> Her kritik karar kanıta dayalı; kaynaklar bölüm sonunda.

---

## 0. Bağlam (ürün özeti)

ADALET-AGENT: Türkçe hukuk AI vatandaş asistanı. Kullanıcı hukuki soru sorar; sistem
**kaynaklı** (kanun maddesi + Yargıtay/Danıştay kararı), **güven skorlu**, **doğrulanmış**
(halüsinasyon yaparsa cevabı reddeder) yanıt döner. SSE streaming: `triage → sources →
drafting → timing → final` event'leri.

**Tasarım sistemi (sabit):**
- Renk: `--bg #0A1628` (deep navy) · `--accent #D4A574` (brushed gold, max %15 alan) ·
  `--text #F5F0E8` (warm cream) · `--danger #C73E3E` · `--success #5C8C5A` (muted sage)
- Tipografi: başlık **Cormorant Garamond**, gövde **Inter**, madde no/kod **JetBrains Mono**
- Stil: glassmorphism kartlar (backdrop-blur), dark cinematic, editorial luxury

---

## 1. Layout — İki Panel (chat + kaynaklar)

**Doğrulandı (3-0):** Sol sohbet + sağ kaynak paneli sektör standardı (Perplexity, Claude Artifacts).

```
┌──────────────────────────────────────────────────────────────┐
│  ÜST BAR (56px)  ADALET ⚖️        [domain çipi]   [Ahmet ▾]   │
├───────────────────────────────────┬──────────────────────────┤
│                                   │ ║ (resize handle 4px)     │
│   SOHBET PANELİ                   │   KAYNAK PANELİ           │
│   flex: 1  (~%60-62)              │   ~%38-40                 │
│   min-width: 0                    │   min: 320px              │
│   overflow-y: auto                │   overflow-y: auto        │
│                                   │                          │
│   [mesaj akışı]                   │   [kaynak kartları]       │
│                                   │   [güven skoru]           │
│                                   │                          │
├───────────────────────────────────┴──────────────────────────┤
│   GİRDİ ÇUBUĞU (sticky bottom)   [Sorunuzu yazın...]   [→]    │
└──────────────────────────────────────────────────────────────┘
```

**CSS iskeleti (Every Layout sidebar deseni — doğrulandı 3-0):**
```css
.sor-container { display: flex; height: 100dvh; overflow: hidden; }
.chat-panel    { flex: 1; min-width: 0; overflow-y: auto; }      /* esnek */
.source-panel  { flex-basis: 38%; min-inline-size: 320px; max-inline-size: 560px;
                 overflow-y: auto; }
.resize-handle { width: 4px; cursor: col-resize; background: var(--glass-border); }
```

**Oran:** Masaüstü sohbet **~%60-62**, kaynaklar **~%38-40**. Kullanıcı resize handle ile
ayarlayabilir (kaydet → localStorage). Araştırma %25-75 aralığını destekliyor; chat-öncelikli
ürün için %60/40 pratik başlangıç.

### Responsive (doğrulandı 3-0)
| Genişlik | Davranış |
|----------|----------|
| **≥ 1024px** | İki panel yan yana + resize handle |
| **768–1024px** | İki panel ama resize handle gizli, kaynaklar %40 sabit |
| **< 768px** | **Tek panel.** Kaynak paneli yan yana DEĞİL → cevap altında `[📚 Kaynaklar (3)]` çipi → tıkla → **bottom-sheet / tam-ekran overlay + backdrop**. Resize handle gizli. |

> Flutter mobil: 600px logical-pixel breakpoint (Row → drawer/overlay).
> Gerçek dual-content için 840px (MD3 expanded) daha iyi eşik olabilir — içeriğe göre ayarla.

---

## 2. Streaming UX — 13 Saniyelik Beklemeyi Yönetmek

**Doğrulandı (3-0):** 13s, Nielsen'in **10+sn "Execution" eşiğinde** → progress bar + yüzde +
**aşamalı durum mesajı** zorunlu. Generic spinner YASAK — anlamlı etiket kullan.

**Kritik (3-0):** Kaynaklar metinden **ÖNCE** gelir (Perplexity deseni, SSE akışınızla birebir).

### 4-Aşamalı Stepper (SSE event → görünür durum)

```
①━━━━②━━━━③━━━━④
triage  sources  drafting  final

①  "Sorunuz sınıflandırılıyor..."        (triage event)
②  "Kaynaklar aranıyor: kanun + Yargıtay" (sources event → SAĞ PANELDE kart skeleton'ları belirir)
③  "Cevap hazırlanıyor..."                (drafting event → typewriter/delta akışı başlar)
④  "Doğrulanıyor..."                      (final event → güven skoru + disclaimer yerleşir)
```

- Üstte ince **determinate progress bar** (4 adım = %25/%50/%75/%100 algısı).
- Her adımın **anlamlı etiketi** olsun (uxtigers: "Analyzing data" tipi, spinner değil).
- **Progressive disclosure (3-0):** "ana yemekten önce mezeler" — kaynak kartları (②) cevap
  metni (③) gelmeden gösterilir; kullanıcı beklerken okumaya başlar.
- **first_token_ms** (SSE timing) gelince typewriter başlat → algılanan latans düşer.

> ⚠️ **Skeleton uyarısı:** "Skeleton ekranlar yüklemeyi hızlı hissettirir" iddiası araştırmada
> **çürütüldü (1-2)**. Skeleton'a "hız" için güvenme; asıl kaldıraç **progress + anlamlı etiket**.
> Skeleton'ı yalnız kaynak kartı yer-tutucusu olarak kullan, sihir bekleme.

---

## 3. Citation (Kaynak Gösterimi)

**Doğrulandı (3-0):** Numaralı inline `[1]` marker → `id` alanı üzerinden kaynak kartına bağlanır.

### Dual-mode etkileşim (3-0, ChatGPT/Copilot standardı)
- **Hover** → küçük popover: kaynak başlığı + ilk satır + tür rozeti (`Kanun` / `Yargıtay`)
- **Tıklama** → sağ panelde ilgili karta **scroll + highlight** (veya resmi mevzuat.gov.tr linki)

### Tam-pasaj kuralı (3-0)
Factual iddialar için **geniş doküman değil, tam pasaj** göster:
- Kanun: `TKHK Madde 11/1` (tam fıkra, alıntıyla)
- Yargıtay: `3. HD · 2023/1234 E. · 2023/5678 K.` + ilgili paragraf alıntısı (genel dosya değil)

### Anti-halüsinasyon (3-0, SIFIR HALÜSİNASYON kuralınızla örtüşür)
Kaynak URL/referansları **ASLA modelden** alınmaz — yalnız doğrulanmış `sources` event'inden.
Model'in ürettiği `[src: id]` etiketi backend'in doğruladığı kaynağa map edilir.

### Kaynak kartı anatomisi (sağ panel)
```
┌──────────────────────────────────────┐
│ [Kanun]  TKHK Madde 11        ✓ Doğru │  ← tür rozeti + doğrulama
│ ────────────────────────────────────  │
│ "Malın ayıplı olması durumunda        │  ← tam pasaj alıntısı
│  tüketici seçimlik haklarını..."      │
│                                        │
│ mevzuat.gov.tr ↗        İlgili: [1][3] │  ← resmi link + hangi cümlelerde geçti
└──────────────────────────────────────┘
```
- `✓ Doğrulandı` rozeti **muted sage `#5C8C5A`** (success). "mevzuat.gov.tr ile metin eşleşti".
- Tür rozeti: `Kanun` (gold) / `Yargıtay` / `Danıştay`.

---

## 4. Trust UI — Güven, Disclaimer, Reddetme

### 4.1 Kaynak şeffaflığı = en değerli (3-0)
**Stanford A2J:** Kaynak/citation linkleri en çok istenen iyileştirme (**5.3/6**). Tasarımınızın
kaynak-paneli-önce yaklaşımı bunu doğruluyor — kaynakları öne çıkar.

### 4.2 Statik disclaimer zayıf → bağlamsal uyarı ekle (3-0)
Statik uyarı etiketleri **3.9/6** (kullanıcılar görmezden gelir). Yapılacak:
- **Zorunlu disclaimer** her cevap altında KALSIN (CLAUDE.md §2 kuralı) — ama tek savunma olmasın.
- **Ek olarak:** risk-anahtar-kelime tetikli **bağlamsal kart** göster. Kullanıcı sorusunda/cevapta
  `tebliğ`, `süre`, `zamanaşımı`, `duruşma günü`, `icra` geçerse → vurgulu kart:
  > ⏱ *"Bu konuda yasal süre olabilir — gecikme hak kaybına yol açabilir. Bir an önce avukata danışın."*

### 4.3 Doğrulama rozeti (2-1, orta-güçlü)
Ham yüzde yanında **"✓ Uzman/kaynak onaylı"** rozeti (Stanford 4.3/6). Sağ panel kartlarında
`Doğrulandı ✓` (sage). Genel güven skoruyla birlikte.

### 4.4 Güven skoru görselleştirme — NÜANSLI (3-0)
**JMIR çalışması (kritik bulgu):**
- Doğru cevapta **sade tek-renk yeşil** güveni artırır.
- **Karışık-renkli belirsizlik** gösterimi, AI **haklı olsa bile** güveni düşürür.
- **Kendinden emin HATA**, belirsizlik gösterilen hatadan **çok daha fazla** güven kırar.

**Uygulama:**
- Yüksek güven (≥%70): **sade sage bar + yüzde**, fazla görsel gürültü yok.
- Orta güven (%40-70): nötr gold ton, "kısmen doğrulandı" notu.
- Düşük/reddedilen: aşağıdaki nazik reddetme kartı (asla kırmızı korkutma).

```
Güven: ▓▓▓▓▓▓▓░░░  %72   ✓ 3 kaynakla doğrulandı
```

### 4.5 Reddetme kartı — KORKUTMADAN (3-0, en kritik trust kararı)
Veto tetiklenince (halüsinasyon riski) sistem reddeder. Bu durum **kırmızı/alarm DEĞİL**,
nazik ve kalibre:

```
┌──────────────────────────────────────────┐
│  🤔  Bu konuda emin değilim               │  ← ikon nötr, başlık sakin (sage/gold, kırmızı değil)
│                                            │
│  Sorunuzu güvenilir kaynaklarla            │
│  doğrulanmış şekilde yanıtlayamadım.       │
│  Yanlış bilgi vermektense, bir avukata     │
│  danışmanızı öneririm.                     │
│                                            │
│  [Soruyu yeniden yaz]  [Avukat bul ↗]     │
└──────────────────────────────────────────┘
```
> Bu, "kendinden emin yanlış cevap"tan kaçınmanın UI karşılığı — araştırma bunun
> halüsinasyon kuralı kadar önemli olduğunu gösteriyor.

---

## 5. Netleştirme (Clarify) Kartı

`clarify` event'i gelince cevap değil **soru kartı** render et (stalled-answer ile karışmasın):
```
┌──────────────────────────────────────────┐
│  Size daha iyi yardımcı olmak için:        │
│  1. Kira sözleşmeniz hâlâ devam ediyor mu? │  ← buton/seçim
│  2. Evi tahliye ettiniz mi?                │
│  [Yanıtla →]                               │
└──────────────────────────────────────────┘
```

---

## 6. Zengin Boş Durum (ilk açılış, ayrı dashboard YOK)

```
        Merhaba, size nasıl yardımcı olayım?       ← Cormorant Garamond, sıcak

   ┌─────────────────────────────────────────┐
   │  Hukuki sorunuzu yazın...           🔍   │     ← büyük, odakta
   └─────────────────────────────────────────┘

   Hızlı başlangıç:
   [🏠 Kira] [💼 İş] [🛒 Tüketici] [🚗 Trafik] [💰 Vergi] ...

   Örnek sorular:
   › "Depozitomu geri alamıyorum"
   › "İşten çıkarıldım, tazminat alabilir miyim?"

   ──────────────────
   Son konuşmalar:  › Kira artışı itirazı   2 gün önce
```

---

## 7. Bileşen Envanteri (Next.js + shadcn)

| Bileşen | Sorumluluk | İlgili SSE/veri |
|---------|-----------|-----------------|
| `ChatStream` | Sol panel mesaj akışı | tüm event'ler |
| `MessageBubble` | Kullanıcı/asistan balonu | — |
| `AnswerCard` | Yapılandırılmış cevap (Kısa cevap/Dayanak/Ne yapmalı) | `final` |
| `StreamStepper` | 4-aşamalı durum + progress | `triage/sources/drafting/final` |
| `CitationMarker` | Inline `[1]` + hover popover | citations |
| `SourcePanel` | Sağ panel | `sources` |
| `SourceCard` | Tek kaynak (tür rozeti + pasaj + doğrulama) | citations |
| `ConfidenceBar` | Güven skoru (sade, nüanslı) | `confidence` |
| `RejectCard` | Nazik reddetme | `verdict==reject` |
| `ClarifyCard` | Netleştirme soruları | `clarify` |
| `RiskWarning` | Bağlamsal süre/tebligat uyarısı | keyword tetikli |
| `DisclaimerBar` | Zorunlu hukuki uyarı | her pass cevap |

---

## 8. Erişilebilirlik (WCAG) — ⚠️ DOĞRULANMASI GEREKEN

Araştırma glassmorphism + dark luxury için **kontrast verisi doğrulayamadı** (açık soru). Zorunlu kontroller:
- **Gövde metni** `#F5F0E8` on `#0A1628` → WCAG AA için **≥ 4.5:1** olmalı. Test et. (ilk bakışta geçer ama cam yüzeyde değişir)
- **Gold accent** `#D4A574` küçük metinde kontrast düşük olabilir → büyük metin/ikon dışında gövdede kullanma (≥3:1 yalnız büyük metin).
- **Cam kartlar:** backdrop-blur arkası değişken → kartın **altına yarı-opak katman** koy ki metin kontrastı arka plandan bağımsız sabit kalsın (axesslab önerisi).
- Stresli/düşük-okuryazar kullanıcı: kısa cümle, büyük dokunma hedefi (≥44px), net hiyerarşi.
- Klavye: citation marker'lar focusable, hover popover keyboard'la da açılır.
- `prefers-reduced-motion`: typewriter/animasyonları kapat.

---

## 9. Açık Sorular (tasarım sırasında karar ver)
1. **Güven skoru formatı:** yatay bar mı, dairesel gauge mi, sadece yüzde mi? (JMIR: sade tek-renk iyi; blind-test'inizde A/B'leyin)
2. **Glassmorphism kontrastı:** warm-cream-on-navy + cam yüzey AA geçiyor mu? (ölç)
3. **Reddetme durumunda sağ panel:** boş mu, "baktığımız ama eşleşmeyen kaynaklar" şeffaflığı mı?
4. **Determinate progress %:** LLM token akışı non-deterministik → 4-adım stepper "determinate algı" verir, gerçek % zaman tahmini gerekmez.

---

## Kaynaklar (doğrulanmış)
- Perplexity streaming-citations cookbook (primary) — kaynak-önce akış, citation mapping, anti-halüsinasyon
- OpenAI ChatGPT docs — hover-preview/click-source dual mode
- Stanford Legal Design Lab A2J class report (primary) — kaynak link 5.3/6, disclaimer 3.9/6, checkmark 4.3/6
- JMIR Human Factors 2025 (PMC11862782, primary) — belirsizlik görselleştirme, kendinden-emin hata
- Every Layout (sidebar), artifactuse panel docs, Ant Design Layout — iki-panel + responsive
- smart-interface-design-patterns, uxtigers — bekleme eşikleri, progressive disclosure
- codewithandrea — Flutter 600px split-view; axesslab — glassmorphism erişilebilirlik
- shapeof.ai/patterns/citations — citation yerleşim/etkileşim

> **Kanıt sınırları:** Trust-UI'nin en güçlü ampirik kaynağı (JMIR) eczacılık alanında (N=30,
> exploratory) — yön doğru, kesin reçete değil. Glassmorphism WCAG dengesine dair doğrulanmış
> spesifik ölçü yok → kontrastı kendin test et. %60/40 oran ve 768px eşik standart ama
> içeriğe göre ayarlanmalı.
