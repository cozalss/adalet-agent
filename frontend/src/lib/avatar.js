/* ADALET — deterministik kullanıcı avatarı (isimden türeyen zarif gradient + baş harf).

   Referans teknik: boring-avatars (github.com/boringdesigners/boring-avatars) —
   isim → stabil tohum → renk. ADALET'in editorial-luxury paletine uyarlandı:
   derin jewel/metal gradient çiftleri, cream baş harf, sol-üst cam parlaması (gem hissi).
   Aynı kullanıcı HER ZAMAN aynı avatarı alır (tohum stabil). */

// Editorial-luxury gradient çiftleri — her biri cream/white baş harfle yüksek kontrast.
// Derin jewel + sıcak metal tonları (neon yok; ADALET kimliğine yakışır).
const PAIRS = [
  ["#d8a24a", "#9c5732"], // gold → bronze (marka)
  ["#3a5a8c", "#14233c"], // navy
  ["#6d3b5e", "#3a2138"], // plum
  ["#3a6b4f", "#1f4534"], // forest
  ["#8a3a4a", "#531e2a"], // burgundy
  ["#2f6f6f", "#163a3a"], // teal
  ["#4a5a78", "#262e40"], // slate
  ["#b07a45", "#6f4226"], // amber
  ["#54499a", "#2a2455"], // indigo
  ["#a85d4a", "#5f3024"], // terracotta
];

/** Stabil string hash (FNV-1a) → 32-bit unsigned. */
function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Avatar tohumu: ad → görünen ad → e-posta → sub. Stabil + küçük harfe indirgenmiş. */
export function avatarSeed(user, prefs) {
  const raw = user?.name || prefs?.displayName || user?.email || user?.sub || "ADALET";
  return String(raw).trim().toLocaleLowerCase("tr-TR") || "adalet";
}

/** Baş harf (TR-aware büyük harf). Boşsa "A". */
export function avatarInitial(seed) {
  const ch = String(seed || "").trim()[0] || "A";
  return ch.toLocaleUpperCase("tr-TR");
}

/** Tohumdan zarif gradient stili (deterministik): marka gradyanı + cam parlaması + açı.
 *  @returns {{backgroundImage: string}} inline style parçası */
export function avatarStyle(seed) {
  const h = hashStr(seed || "adalet");
  const [from, to] = PAIRS[h % PAIRS.length];
  const angle = 105 + (h % 60); // 105–164° — her tohum biraz farklı yön
  return {
    backgroundImage:
      // üst katman: sol-üstten cam parlaması (gem/coin derinliği)
      "radial-gradient(120% 120% at 28% 22%, rgba(255,255,255,.34), rgba(255,255,255,0) 42%)," +
      // alt katman: kişiye özel jewel/metal gradyanı
      `linear-gradient(${angle}deg, ${from}, ${to})`,
  };
}
