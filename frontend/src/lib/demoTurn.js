/* Önizleme/demo turn — `?preview=1` ile yüklenir (App.jsx).

   Amaç: backend olmadan tam cevap UI'ını göstermek. Tasarım QA + Teknofest jüri
   demosu (lokal model/Qdrant kurmadan akışı sergilemek) için. Production'da
   yalnız URL'de ?preview=1 varsa devreye girer — normal kullanıcı görmez.
   Veri SAHTEDİR (gerçek karar/madde uydurması değil — açıkça örnek). */
export const DEMO_TURN = {
  key: 1,
  question: "2 yıl çalıştığım işten çıkarıldım, kıdem tazminatım ne kadar olur?",
  phase: "final",
  data: {
    kind: "answer",
    domain: "İş Hukuku",
    domainConfidence: 0.91,
    sources: [
      {
        id: 1, type: "Kanun", badge: "kanun",
        title: "İş Kanunu m.14 — Kıdem tazminatı", ref: "1475 / m.14",
        passage: "İşçinin işe başladığı tarihten itibaren hizmet akdinin devamı süresince her geçen tam yıl için 30 günlük ücreti tutarında kıdem tazminatı ödenir.",
        url: "https://mevzuat.gov.tr", verified: true, rel: [1],
      },
      {
        id: 2, type: "Yargıtay", badge: "yargitay",
        title: "Yargıtay 9. Hukuk Dairesi 2019/1234", ref: "Y9HD 2019/1234",
        passage: "Kıdem tazminatı hesabında işçinin son giydirilmiş brüt ücreti esas alınır; ikramiye ve düzenli ödemeler dâhildir.",
        url: "", verified: true, rel: [2],
      },
    ],
    answer: {
      confidence: 86, text: "2 yıl çalıştıysanız kıdem tazminatına hak kazanırsınız...",
      sections: [
        { label: "Kısa cevap", lead: true, runs: [
          { t: "2 yıl çalıştıysanız kıdem tazminatına hak kazanırsınız" }, { cite: 1 },
          { t: ". Tutar, her tam yıl için 30 günlük giydirilmiş brüt ücretiniz kadardır" }, { cite: 2 }, { t: "." },
        ] },
        { label: "Ne yapmalı", steps: [
          "İşten çıkış belgenizi ve son 3 ayın bordrolarını toplayın.",
          "İşverenden kıdem tazminatınızı yazılı olarak talep edin.",
          "Ödenmezse İş Mahkemesi'ne başvurun (zamanaşımı 5 yıl).",
        ] },
      ],
    },
    risk: { keyword: "süre", text: "Kıdem tazminatında <b>zamanaşımı 5 yıldır</b> — gecikme hak kaybına yol açabilir." },
    disclaimers: ["Bu yanıt genel bilgilendirme amaçlıdır, hukuki danışmanlık veya avukatlık hizmeti yerine geçmez. Somut durumunuz için bir avukata başvurun."],
    claims: [
      { text: "2 yıl çalışan işçi kıdem tazminatına hak kazanır.", verified: true, score: 94, reason: "İş Kanunu m.14 metniyle birebir eşleşme doğrulandı.", citeNums: [1] },
      { text: "Her tam yıl için 30 günlük giydirilmiş brüt ücret ödenir.", verified: true, score: 88, reason: "Yargıtay 9. HD kararıyla teyit edildi.", citeNums: [2] },
      { text: "İhbar tazminatı da her durumda otomatik ödenir.", verified: false, score: 31, reason: "Kaynaklarda doğrulanamadı — bildirim süresine ve fesih şekline bağlı.", citeNums: [] },
    ],
    debateNotes: "Mevzuat ve Emsal ajanları hemfikir; Doğrulama ajanı 3. iddiayı kaynak eşleşmesi olmadığı için işaretledi, taslaktan çıkarıldı.",
    retryCount: 1,
    prediction: {
      verdictClass: "kazandi", confidence: 78,
      similarCaseIds: ["Y9HD 2019/1234", "Y22HD 2020/5567", "Y9HD 2021/8890"],
      reasoning: "Benzer nitelikteki 12 emsal davadan 9'u işçi lehine sonuçlanmış.",
      disclaimer: "Bu tahmin geçmiş Yargıtay kararlarından türetilmiş istatistiksel bir tahmindir; mahkeme sonucu garantisi DEĞİLDİR. Kesin değerlendirme için bir avukata danışın.",
    },
    conversationId: "preview-demo",
    hasDilekce: true,
  },
};
