/* ADALET kullanıcı tercihleri — localStorage birincil + DOM uygulama + Supabase senkron.

   Tercihler (görünen ad, yazı boyutu, hareket, kontrast, tercih alanları) öncelikle
   TARAYICIDA (localStorage) tutulur — yerelde anında çalışır. Kayıtlı
   kullanıcıda DOĞRUDAN Supabase profiles (+ RLS) ile cihazlar-arası senkronlanır
   (best-effort; oturumsuzda sessizce yerel kalır). Eski FastAPI /me/preferences yolu
   kaldırıldı (v2.2 tam geçiş).

   Uygulama: tercihler <html> data-attribute'larına yansır; görsel etki CSS'te
   (data-text-scale / data-reduce-motion / data-contrast). */
import { useState, useEffect, useCallback, useRef } from "react";
import { loadPrefsSb, upsertPrefsSb, clearPrefsSb, onAuthChange } from "../lib/supabaseData.js";

const KEY = "adalet.prefs";
const SCHEMA_V = 1;

export const DEFAULT_PREFS = Object.freeze({
  v: SCHEMA_V,
  displayName: "",
  textScale: "normal", // "compact" | "normal" | "large"
  reduceMotion: false,
  highContrast: false,
  preferredDomains: [], // 8 sivil alandan çoklu seçim (boş = hepsi)
});

const TEXT_SCALES = new Set(["compact", "normal", "large"]);
const ALLOWED_DOMAINS = new Set([
  "tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari",
]);

/** Bilinmeyen/eski alanları kırp + sınırla (forward-compat + savunmacı). Test için export. */
export function sanitize(raw) {
  const p = raw && typeof raw === "object" ? raw : {};
  const domains = Array.isArray(p.preferredDomains)
    ? p.preferredDomains.filter((d) => ALLOWED_DOMAINS.has(d)).slice(0, 8)
    : [];
  return {
    v: SCHEMA_V,
    displayName: typeof p.displayName === "string" ? p.displayName.slice(0, 60) : "",
    textScale: TEXT_SCALES.has(p.textScale) ? p.textScale : "normal",
    reduceMotion: !!p.reduceMotion,
    highContrast: !!p.highContrast,
    preferredDomains: [...new Set(domains)],
  };
}

function readLocal() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? sanitize(JSON.parse(raw)) : { ...DEFAULT_PREFS };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

function writeLocal(prefs) {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* özel mod */ }
}

/** Tercihleri <html> data-attribute'larına yansıt (CSS görsel etkiyi alır). */
function applyToDom(prefs) {
  if (typeof document === "undefined") return;
  const el = document.documentElement;
  el.setAttribute("data-text-scale", prefs.textScale);
  if (prefs.reduceMotion) el.setAttribute("data-reduce-motion", "");
  else el.removeAttribute("data-reduce-motion");
  if (prefs.highContrast) el.setAttribute("data-contrast", "high");
  else el.removeAttribute("data-contrast");
}

/** Backend payload — yerel şemadan sunucu alan adlarına (snake_case) çevir. */
function toServer(p) {
  return {
    display_name: p.displayName,
    text_scale: p.textScale,
    reduce_motion: p.reduceMotion,
    high_contrast: p.highContrast,
    preferred_domains: p.preferredDomains,
  };
}

/** Sunucu payload'ından yerel şemaya. */
function fromServer(s) {
  return sanitize({
    displayName: s.display_name,
    textScale: s.text_scale,
    reduceMotion: s.reduce_motion,
    highContrast: s.high_contrast,
    preferredDomains: s.preferred_domains,
  });
}

export function usePrefs() {
  const [prefs, setPrefs] = useState(readLocal);
  const mounted = useRef(false);
  // Uzak senkron kaynaklı setPrefs sonrası gereksiz geri-PUT'u (sunucudan gelen
  // veriyi sunucuya yazma) atlamak için işaret.
  const fromRemote = useRef(false);

  // İlk yüklemede DOM'a uygula + (kayıtlıysa) Supabase tercihini çek; girişte yenile.
  useEffect(() => {
    applyToDom(prefs);
    let cancelled = false;
    let syncId = 0; // geride kalan/eski oturum response'unu at (yarış koruması).
    async function pullRemote() {
      const mine = ++syncId;
      const remote = await loadPrefsSb(); // oturumsuzda null → no-op
      if (cancelled || mine !== syncId || !remote) return;
      const merged = fromServer(remote);
      fromRemote.current = true; // sonraki effect bu değişimi yazma atlasın
      setPrefs(merged);
      writeLocal(merged);
      applyToDom(merged);
    }
    // Çıkışta tercihleri varsayılana sıfırla + yereli temizle (cihaz paylaşımı).
    function clearLocal() {
      syncId += 1;
      try { localStorage.removeItem(KEY); } catch { /* özel mod */ }
      fromRemote.current = true; // default'a dönüş sunucuya geri-yazılmasın
      const fresh = { ...DEFAULT_PREFS };
      setPrefs(fresh);
      applyToDom(fresh);
    }
    pullRemote();
    const off = onAuthChange((event) => {
      if (event === "SIGNED_OUT") clearLocal();
      else pullRemote(); // SIGNED_IN → yeni oturumun tercihlerini getir
    });
    return () => { cancelled = true; off(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Değişimde: DOM uygula + yerel kaydet + (best-effort) sunucuya yaz.
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    applyToDom(prefs);
    writeLocal(prefs);
    if (fromRemote.current) { fromRemote.current = false; return; } // uzaktan geldi → yazma atla
    upsertPrefsSb(toServer(prefs)); // oturumsuzda sessizce no-op
  }, [prefs]);

  /** Tek alan güncelle (immutable). */
  const setPref = useCallback((key, value) => {
    setPrefs((prev) => sanitize({ ...prev, [key]: value }));
  }, []);

  /** Tercih edilen alanı aç/kapat (çoklu seçim çipi). */
  const toggleDomain = useCallback((id) => {
    setPrefs((prev) => {
      const has = prev.preferredDomains.includes(id);
      const next = has
        ? prev.preferredDomains.filter((d) => d !== id)
        : [...prev.preferredDomains, id];
      return sanitize({ ...prev, preferredDomains: next });
    });
  }, []);

  /** "Tüm verilerimi sil": yerel + Supabase kaydını temizle, varsayılana dön. */
  const clearAll = useCallback(() => {
    try { localStorage.removeItem(KEY); } catch { /* yoksay */ }
    clearPrefsSb(); // oturumsuzda no-op
    const fresh = { ...DEFAULT_PREFS };
    setPrefs(fresh);
    applyToDom(fresh);
  }, []);

  return { prefs, setPref, toggleDomain, clearAll };
}
