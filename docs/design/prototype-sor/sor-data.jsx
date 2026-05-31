/* ============================================================
   ADALET /sor — icons + mock SSE scenario data
   ============================================================ */

/* ---------- Line icons (no emoji, editorial) ---------- */
const Icon = {
  scale: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 6a3 3 0 0 0 5 0L5 7zM19 7l-2.5 6a3 3 0 0 0 5 0L19 7zM12 5l-7 2M12 5l7 2" />
    </svg>
  ),
  send: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M5 12h13M12 5l7 7-7 7" />
    </svg>
  ),
  search: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
    </svg>
  ),
  check: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M5 12.5l4.5 4.5L19 6.5" />
    </svg>
  ),
  ext: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M14 5h5v5M19 5l-8 8M11 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5" />
    </svg>
  ),
  clock: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" />
    </svg>
  ),
  book: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2V5zM8 3v14" />
    </svg>
  ),
  help: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="12" cy="12" r="9" /><path d="M9.2 9.3a2.8 2.8 0 0 1 5.4 1c0 1.9-2.8 2.5-2.8 2.5M12 17h.01" />
    </svg>
  ),
  info: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" />
    </svg>
  ),
  home: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 11l8-7 8 7M6 10v9h12v-9" />
    </svg>
  ),
  bag: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M6 8h12l-1 12H7L6 8zM9 8V6a3 3 0 0 1 6 0v2" />
    </svg>
  ),
  cart: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 5h2l2 11h9l2-7H7M9 20h.01M17 20h.01" />
    </svg>
  ),
  car: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11M4 11h16v5H4zM7 16v2M17 16v2M7 13h.01M17 13h.01" />
    </svg>
  ),
  coin: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="12" cy="12" r="9" /><path d="M12 7v10M9.5 9.2A2.4 2.4 0 0 1 12 7.5c1.4 0 2.5.8 2.5 1.9M14.5 14.8A2.4 2.4 0 0 1 12 16.5c-1.4 0-2.5-.8-2.5-1.9" />
    </svg>
  ),
  plus: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" {...p}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  pencil: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3zM14 7l3 3" />
    </svg>
  ),
  panel: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9 4v16" />
    </svg>
  ),
  mic: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M6 11a6 6 0 0 0 12 0M12 17v4" />
    </svg>
  ),
  wave: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" {...p}>
      <path d="M5 10v4M9 7v10M13 9v6M17 6v12M21 10v4" />
    </svg>
  ),
  pin: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6zM12 15v5" />
    </svg>
  ),
  dots: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" {...p}>
      <circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" />
    </svg>
  ),
  grid: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="6.5" cy="6.5" r="2" /><circle cx="17.5" cy="6.5" r="2" /><circle cx="6.5" cy="17.5" r="2" /><circle cx="17.5" cy="17.5" r="2" />
    </svg>
  ),
  image: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" /><circle cx="8.5" cy="10" r="1.6" /><path d="M21 16l-5-5L5 19" />
    </svg>
  ),
  chevron: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  ),
};

/* ---------- Sidebar recent chats (legal topics) ---------- */
const SB_NAV = [
  { id: "new", label: "Yeni sohbet", icon: "pencil" },
  { id: "search", label: "Sohbetlerde ara", icon: "search" },
  { id: "library", label: "Kaynaklar", icon: "book" },
  { id: "projects", label: "Dosyalarım", icon: "grid" },
];

const SB_CHATS = [
  { t: "Ayıplı telefon iadesi", pin: true },
  { t: "Kira artış oranı itirazı", pin: true },
  { t: "Tahliye taahhüdü süresi", pin: true },
  { t: "Fazla mesai ücreti hesabı" },
  { t: "Tüketici hakem heyeti başvurusu" },
  { t: "İş sözleşmesi feshi tazminat" },
  { t: "Trafik cezası itiraz dilekçesi" },
  { t: "Miras paylaşımı saklı pay" },
  { t: "Kira sözleşmesi depozito iadesi" },
  { t: "Whatsapp delil niteliği" },
  { t: "Nafaka artırım davası" },
  { t: "Tüketici kredisi cayma hakkı" },
];

const CG_SUGGEST = [
  { label: "Dilekçe taslağı", icon: "pencil" },
  { label: "Hakkımı öğren", icon: "scale" },
  { label: "Süre / zamanaşımı sor", icon: "clock" },
];

/* ---------- Quick-start domains (empty state) ---------- */
const DOMAINS = [
  { id: "kira", label: "Kira", icon: "home" },
  { id: "is", label: "İş", icon: "bag" },
  { id: "tuketici", label: "Tüketici", icon: "cart" },
  { id: "trafik", label: "Trafik", icon: "car" },
  { id: "vergi", label: "Vergi", icon: "coin" },
];

const RECENTS = [
  { t: "Kira artışı itirazı", when: "2 gün önce" },
  { t: "Fazla mesai ücreti hesabı", when: "5 gün önce" },
];

/* ---------- Scenario builders ----------
   Each scenario drives the SSE-style stream:
   triage → sources → drafting → final
-------------------------------------------*/

const SCN_AYIPLI = {
  id: "ayipli",
  kind: "answer",
  domain: "Tüketici Hukuku",
  question: "İnternetten aldığım telefon iki gün sonra bozuldu, ne yapabilirim?",
  triageLabel: "Soru sınıflandırılıyor — Tüketici Hukuku",
  risk: {
    keyword: "süre",
    text: "Ayıp bildiriminde <b>süre</b> önemlidir — gecikme hak kaybına yol açabilir. Ayıbı fark eder etmez satıcıya yazılı bildirim yapın.",
  },
  sources: [
    {
      id: 1, type: "Kanun", badge: "kanun",
      title: "TKHK Madde 11", ref: "6502 s. Kanun · m.11",
      passage: "Malın ayıplı olduğunun anlaşılması hâlinde tüketici; satılanı geri vermeye hazır olduğunu bildirerek sözleşmeden dönme, ayıpsız misli ile değişim, ücretsiz onarım veya bedel indirimi seçimlik haklarından birini kullanabilir.",
      url: "mevzuat.gov.tr",
      verified: true, rel: [1],
    },
    {
      id: 2, type: "Kanun", badge: "kanun",
      title: "TKHK Madde 10", ref: "6502 s. Kanun · m.10/2",
      passage: "Teslim tarihinden itibaren altı ay içinde ortaya çıkan ayıpların, teslim tarihinde var olduğu kabul edilir. Bu durumda malın ayıplı olmadığının ispatı satıcıya aittir.",
      url: "mevzuat.gov.tr",
      verified: true, rel: [2],
    },
    {
      id: 3, type: "Yargıtay", badge: "yargitay",
      title: "Yargıtay 3. HD", ref: "2022/4521 E. · 2022/8934 K.",
      passage: "Tüketicinin seçimlik haklarını kullanması için ayıbın gizli ayıp niteliğinde olması yeterlidir; satıcı, malın ayıpsız olduğunu ispat edemediği takdirde tüketici lehine karar verilir.",
      url: "karararama.yargitay.gov.tr",
      verified: true, rel: [3],
    },
  ],
  answer: {
    confidence: 78,
    sections: [
      {
        label: "Kısa cevap", lead: true,
        runs: [
          { t: "Aldığınız telefon ayıplı (kusurlu) çıktığı için seçimlik haklarınız var: ücretsiz onarım, ayıpsız yenisi ile değişim, bedel indirimi veya ürünü iade edip paranızı geri alma." },
          { cite: 1 },
          { t: " Bu hakların hangisini kullanacağınızı siz seçersiniz." },
        ],
      },
      {
        label: "Dayanak",
        runs: [
          { t: "Teslimden itibaren ilk 6 ay içinde ortaya çıkan arızanın baştan var olduğu kabul edilir; ürünün sağlam olduğunu ispat yükü satıcıdadır." },
          { cite: 2 },
          { t: " Yargıtay da gizli ayıpta, satıcı aksini ispatlayamazsa tüketici lehine karar vermektedir." },
          { cite: 3 },
        ],
      },
      {
        label: "Ne yapmalı", steps: [
          "Satıcıya yazılı (e-posta/iadeli taahhütlü) başvurarak seçtiğiniz hakkı bildirin ve makul süre tanıyın.",
          "Sonuç alamazsanız, parasal sınıra göre Tüketici Hakem Heyeti veya Tüketici Mahkemesi'ne başvurun.",
          "Fatura, kargo kaydı ve yazışmaları delil olarak saklayın.",
        ],
      },
    ],
  },
};

const SCN_TAHLIYE = {
  id: "tahliye",
  kind: "clarify",
  domain: "Kira Hukuku",
  question: "Kiracımı evden çıkarmak istiyorum, nasıl yapabilirim?",
  triageLabel: "Soru sınıflandırılıyor — Kira Hukuku",
  clarify: {
    intro: "Size doğru yolu gösterebilmem için birkaç şeyi netleştirelim:",
    options: [
      "Yazılı bir tahliye taahhütnamesi var mı?",
      "Kiracı kira bedelini düzenli ödüyor mu?",
      "Sözleşme süresi doldu mu, yoksa devam mı ediyor?",
    ],
  },
  // after clarify is answered, we resolve to this answer:
  resolved: {
    risk: {
      keyword: "süre",
      text: "Tahliye davalarında <b>süre</b> ve usul kritiktir — örn. tahliye taahhüdünde 1 aylık dava açma süresi. Adım atmadan önce avukata danışmanız önerilir.",
    },
    sources: [
      {
        id: 1, type: "Kanun", badge: "kanun",
        title: "TBK Madde 350", ref: "6098 s. Kanun · m.350",
        passage: "Kiraya veren, kiralananı kendisi veya yakınları için konut ya da işyeri gereksinimi sebebiyle kullanma zorunluluğu varsa, belirli süreli sözleşmelerde sürenin sonunda dava açarak kira sözleşmesini sona erdirebilir.",
        url: "mevzuat.gov.tr", verified: true, rel: [1],
      },
      {
        id: 2, type: "Kanun", badge: "kanun",
        title: "TBK Madde 352", ref: "6098 s. Kanun · m.352/1",
        passage: "Kiracı, kiralananı belli bir tarihte boşaltmayı yazılı olarak üstlendiği hâlde boşaltmazsa kiraya veren, bu tarihten itibaren bir ay içinde icraya başvurarak veya dava açarak tahliyeyi sağlayabilir.",
        url: "mevzuat.gov.tr", verified: true, rel: [2],
      },
    ],
    answer: {
      confidence: 64,
      sections: [
        {
          label: "Kısa cevap", lead: true,
          runs: [
            { t: "Kiracıyı ancak kanunda sayılı haklı sebeplerle çıkarabilirsiniz; bunların başında yazılı tahliye taahhüdü ve gereksinim (ihtiyaç) nedeniyle tahliye gelir." },
            { cite: 1 },
          ],
        },
        {
          label: "Dayanak",
          runs: [
            { t: "Yazılı tahliye taahhüdü varsa, taahhüt edilen tarihten itibaren bir ay içinde icra veya dava yoluna gidebilirsiniz." },
            { cite: 2 },
            { t: " Taahhüt yoksa, gereksinim veya diğer kanuni sebepleri ispat etmeniz gerekir." },
          ],
        },
        {
          label: "Ne yapmalı", steps: [
            "Elinizdeki belgeleri (sözleşme, tahliye taahhüdü, ödeme kayıtları) toplayın.",
            "Taahhüt varsa süreyi kaçırmamak için bir ay içinde icra/dava başlatın.",
            "Sürecin usulden reddedilmemesi için bir avukattan destek alın.",
          ],
        },
      ],
    },
  },
};

const SCN_REJECT = {
  id: "reject",
  kind: "reject",
  domain: "Belirsiz",
  question: "Açacağım davayı kesin kazanır mıyım, hâkim ne karar verir?",
  triageLabel: "Soru sınıflandırılıyor — sonuç tahmini",
  // sources we looked at but couldn't match
  lookedAt: [
    "Genel yargılama usulü hükümleri",
    "Emsal karar veritabanı taraması",
  ],
  reject: {
    title: "Bu konuda emin değilim",
    body: "Bir davanın sonucunu veya hâkimin kararını güvenilir kaynaklarla doğrulanmış şekilde öngöremem; bu, somut delillere ve takdire bağlıdır. Yanlış bir kesinlik vermektense, durumunuzu bir avukatla değerlendirmenizi öneririm.",
  },
};

const SCENARIOS = { ayipli: SCN_AYIPLI, tahliye: SCN_TAHLIYE, reject: SCN_REJECT };

/* map example questions / typed text → scenario id */
function pickScenario(text, forced) {
  if (forced && forced !== "auto" && SCENARIOS[forced]) return forced;
  const s = (text || "").toLowerCase();
  if (/(kirac|tahliye|ev sahib|çıkar)/.test(s)) return "tahliye";
  if (/(kazan|hâkim|hakim|kesin|garanti|ne karar)/.test(s)) return "reject";
  return "ayipli";
}

const EXAMPLES = [
  { t: "İnternetten aldığım telefon iki gün sonra bozuldu, ne yapabilirim?", scn: "ayipli" },
  { t: "Kiracımı evden çıkarmak istiyorum, nasıl yapabilirim?", scn: "tahliye" },
  { t: "Açacağım davayı kesin kazanır mıyım?", scn: "reject" },
];

Object.assign(window, { Icon, DOMAINS, RECENTS, SCENARIOS, pickScenario, EXAMPLES, SB_NAV, SB_CHATS, CG_SUGGEST });
