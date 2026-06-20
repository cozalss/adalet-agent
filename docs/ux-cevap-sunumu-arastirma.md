# Cevap Sunumu UX — Deep-Research Bulguları (2026-06-20)

> Hukuk AI sohbet arayüzünde "en iyi cevap sunumu" için çok-kaynaklı, adversarial-doğrulanmış
> araştırma. 23 kaynak → 111 iddia → 25 doğrulandı (21 onay / 4 çürütme). Aşağıdaki tasarım
> kararları bu kanıtlara dayanır.

## Onaylanan bulgular (≥3-0 oybirliği, aksi belirtilmedikçe)

1. **Satır-içi atıf = numaralı, hover-edilebilir chip'ler** (akademik/Perplexity tarzı), ayrı
   gürültülü kartlar değil; kaynak detayı hover/popover ile (progressive-disclosure). Çoklu
   referans tek kompakt rozette toplanabilir. — *Vercel AI SDK Elements (inline-citation)*

2. **KRİTİK: atıf chip'i güvenilirlik SİNYALİ DEĞİL.** Kullanıcılar atıf içeren çıktıya
   (sahte/ilgisiz olsa bile) körü körüne güvenir; geçerli bir kaynak bile "yanlış-temellendirilmiş"
   (misgrounded) olabilir — uydurmadan daha tehlikeli, çünkü daha ince. → chip'lerin yanında
   **"kaynağı kontrol et"** affordance'ı şart. — *Stanford RegLab/HAI 2025; Ding et al. AAAI 2025*

3. **Ticari hukuk RAG araçları bile sorguların >%17'sinde halüsinasyon üretir** (Lexis+ %17,
   Westlaw %33). → cevabı ASLA otoriter/nihai sunma; "araştırmanın son sözü değil ilk adımı"
   çerçevele. Bu, ADALET'in anti-halüsinasyon katmanını GÖRÜNÜR kılmayı destekler. — *Stanford 2024*

4. **Kalibre edilmemiş güven skoru göstermek NET ZARARLI.** Ham "%61 güven" yorumlanamaz;
   yanlış öneride yüksek skor "algoritmik tiksinme" yaratır. Gösterilecekse **frekans formatı**
   ("100 benzer olayın ~61'i") şart. — *Li et al. CHI 2024; MS Aether*. KARŞI iddia ("güven
   skoru kalibrasyonu iyileştirir") **ÇÜRÜTÜLDÜ 0-3**. "Sayısal > sözel" **ÇÜRÜTÜLDÜ 1-2**.

5. **Meta-kart yığını (güven% + tahmin + ajan-izi) AŞIRI-GÜVENİ artırır** — yanlış cevaba bile
   kör güven dahil. Bilgilendirici-olmayan bir "doğruluk skoru" bile (iddia %50 doğru olsa dahi)
   güveni yükseltti. → minimal, düşük-gürültülü sunum. — *MS Aether (Bussone/Bansal/Lai&Tan)*

6. **Belirsizliği BİRİNCİ-TEKİL dille** ("Bundan tam emin değilim, ancak…") ifade et — aşırı-güveni
   ölçülebilir azaltır, doğruluğu artırır (güven/kullanma-isteği bedeliyle). Genel-perspektif
   ("Açık değil ama…") istatistiksel ANLAMSIZ — **tam dil önemli**. — *Kim et al. FAccT 2024, N=404*

7. **Şeffaflık/doğrulama-izini HER ZAMAN göstermek karar-etkinliğini iyileştirmez** (kalibre
   değilse yetersiz-güvene iter). → **progressive-disclosure**. — *Li et al. 2024*. Harvey
   kara-kutuyu reddeder ama "her zaman görünür doğrulama-izi" iddiası **ÇÜRÜTÜLDÜ 1-2**.

8. **Kullanıcılar atıf + bir güven sinyali İSTER** (N=192'nin %20'si) → tamamen kaldırma da
   beklentiye aykırı. Çözüm: kaldırma değil, **frekans-format + progressive-disclosure + doğal-dil
   hedge**. — *Ryser et al. 2025*

9. **Akan-taslak → doğrulanmış-final geçişine dair DOĞRUDAN UX çalışması YOK** (araştırmanın açık
   noktası). Öneri ilkelerden türetildi: sadelik + in-place tutarlılık + detay-ağır yeniden-düzenin
   zararı → ADALET kendi A/B'sini koşmalı.

## Tasarım kararı (ADALET'e uygulanan)

- **Tek temiz akış:** taslak akarken bile final layout'ta render; doğrulama sırasında kart-ağırlıklı
  yeniden-düzene GEÇME → in-place settle + kısa "doğrulanıyor" mikro-durumu.
- **Atıf:** AnswerCard satır-içi chip + altta sade "Kaynaklar (N)" + "İlgili Kararlar (M)" footer
  bağlantısı (yan panelde detay; on-demand). Gürültülü stat-kartı YOK.
- **Meta (güven% / tahmin / ajan-izi): VARSAYILAN GİZLİ** → tek collapsed "Doğrulama detayları"
  disclosure. Ham "%61 güven" KALDIRILDI (kalibre değil). Tahmin disclosure içine alındı.
- **Hukuki disclaimer** her yanıtta (proje zorunluluğu) + "kaynakları kontrol edin" çerçevesi.

## Kaynaklar (öne çıkan birinci-el)
- Vercel AI SDK Elements — inline-citation (üretim bileşeni)
- Stanford RegLab/HAI — Legal RAG Hallucinations (J. Empirical Legal Studies 2025)
- Li et al. CHI 2024 (arXiv 2402.07632); Kim et al. FAccT 2024; MS Aether Overreliance Review
- Ding et al. AAAI 2025 (2501.01303); Ryser et al. 2025 (2512.09088); Ehsan & Riedl (2109.12480)

*Tam rapor: deep-research workflow wf_65ce7dd6-201 (105 ajan, 6M token).*
