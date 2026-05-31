/* ADALET /sor — line icons (editorial, no emoji) + sidebar/quick data.
   Prototipten birebir taşındı; window global yerine ES export. */
import React from "react";

export const Icon = {
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
  download: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M12 4v11M8 11l4 4 4-4M5 19h14" />
    </svg>
  ),
  chevron: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  ),
  copy: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h8" />
    </svg>
  ),
  stop: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none" />
    </svg>
  ),
  refresh: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M3.5 12a8.5 8.5 0 0 1 14.5-6l2 2M20.5 12a8.5 8.5 0 0 1-14.5 6l-2-2M19 4v4h-4M5 20v-4h4" />
    </svg>
  ),
  like: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M7 10v10H4V10h3zm0 0l4-7a2 2 0 0 1 2 2v3h5a2 2 0 0 1 2 2.3l-1.3 7A2 2 0 0 1 18.7 20H7" />
    </svg>
  ),
  dislike: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M17 14V4h3v10h-3zm0 0l-4 7a2 2 0 0 1-2-2v-3H6a2 2 0 0 1-2-2.3l1.3-7A2 2 0 0 1 7.3 4H17" />
    </svg>
  ),
};

export const SB_NAV = [
  { id: "new", label: "Yeni sohbet", icon: "pencil" },
  { id: "search", label: "Sohbetlerde ara", icon: "search" },
  { id: "library", label: "Kaynaklar", icon: "book" },
  { id: "projects", label: "Dosyalarım", icon: "grid" },
];

export const CG_SUGGEST = [
  { label: "Dilekçe taslağı", icon: "pencil" },
  { label: "Hakkımı öğren", icon: "scale" },
  { label: "Süre / zamanaşımı sor", icon: "clock" },
];

export const DOMAINS = [
  { id: "kira", label: "Kira", icon: "home" },
  { id: "is", label: "İş", icon: "bag" },
  { id: "tuketici", label: "Tüketici", icon: "cart" },
  { id: "trafik", label: "Trafik", icon: "car" },
  { id: "vergi", label: "Vergi", icon: "coin" },
];

export const EXAMPLES = [
  { t: "İnternetten aldığım telefon iki gün sonra bozuldu, ne yapabilirim?" },
  { t: "Kiracımı evden çıkarmak istiyorum, nasıl yapabilirim?" },
  { t: "2 yıl çalıştığım işten çıkarıldım, kıdem tazminatım ne kadar olur?" },
];

// Boş-durum domain kartları — ADALET'in sivil hukuk kapsamını görünür kılar
// (vercel suggested-actions deseni). Her kart örnek soruya eşlenir, gönderir.
export const DOMAIN_CARDS = [
  { icon: "cart", label: "Tüketici", q: "İnternetten aldığım ürün ayıplı çıktı, iade ve para iadesi hakkım var mı?" },
  { icon: "bag", label: "İş", q: "2 yıl çalıştığım işten çıkarıldım, kıdem ve ihbar tazminatım ne kadar olur?" },
  { icon: "home", label: "Kira", q: "Ev sahibim kira artışını çok yüksek tuttu, yasal sınır nedir, itiraz edebilir miyim?" },
  { icon: "car", label: "Trafik", q: "Kusurlu bulunduğum trafik cezasına nasıl ve hangi sürede itiraz edebilirim?" },
];
