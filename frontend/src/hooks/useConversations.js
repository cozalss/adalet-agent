/* ADALET sohbet geçmişi — localStorage birincil + Supabase senkron.

   ADALET artık sohbet geçmişi tutar. Birincil kaynak tarayıcı localStorage
   (misafir de dahil herkeste HEMEN çalışır); kayıtlı kullanıcıda DOĞRUDAN Supabase
   (conversations/messages + RLS) ile cihazlar-arası senkronlanır (best-effort;
   misafirde sessizce no-op). Eski FastAPI /me/* yolu kaldırıldı (v2.2 tam geçiş).

   Türetilen: "Kaynaklar" (tüm sohbetlerdeki atıflar) ve "Dosyalarım" (yüklenen
   belge metadata'sı) bu kayıtlardan üretilir. */
import { useState, useCallback, useEffect, useRef } from "react";
import {
  loadConversationsSb, upsertConversationSb, deleteConversationSb,
  deleteAllConversationsSb, onAuthChange,
} from "../lib/supabaseData.js";
import { searchConversations, aggregateSources, aggregateFiles } from "../lib/conversationUtils.js";

const KEY = "adalet.conversations";
const MAX_CONVERSATIONS = 100; // sınırsız büyümeyi önle

function readAll() {
  try {
    const raw = localStorage.getItem(KEY);
    const obj = raw ? JSON.parse(raw) : {};
    return obj && typeof obj === "object" ? obj : {};
  } catch { return {}; }
}

function writeAll(map) {
  try {
    // En yeni MAX_CONVERSATIONS kaydı tut (eski olanı düş).
    const sorted = Object.values(map).sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""));
    const kept = sorted.slice(0, MAX_CONVERSATIONS);
    const trimmed = Object.fromEntries(kept.map((c) => [c.id, c]));
    localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch { /* özel mod / kota */ }
}

function sortedList(map) {
  return Object.values(map).sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""));
}

export function useConversations() {
  const [map, setMap] = useState(readAll);
  // map'in senkron aynası — yan-etkiler (localStorage + ağ) setMap updater'ı
  // DIŞINDA yapılır (React updater'lar saf olmalı; Strict Mode iki kez çağırır).
  const mapRef = useRef(map);
  useEffect(() => { mapRef.current = map; }, [map]);

  // Aynı sekmenin başka yerinden değişirse senkron tut (storage event).
  useEffect(() => {
    const onStorage = (e) => { if (e.key === KEY) { const m = readAll(); mapRef.current = m; setMap(m); } };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // Cihazlar-arası: kayıtlı kullanıcıda Supabase'ten geçmişi çek + yerelle birleştir.
  // (Çakışmada yenisi kazanır; eşit/yereldeyse zengin yerel turn verisi korunur.)
  useEffect(() => {
    let cancelled = false;
    let syncId = 0; // geride kalan/eski oturum response'unu at (yarış koruması).
    async function sync() {
      const mine = ++syncId;
      const remote = await loadConversationsSb(); // misafirde null → no-op
      if (cancelled || mine !== syncId || !remote) return;
      const local = mapRef.current;
      const merged = { ...local };
      for (const id of Object.keys(remote)) {
        const r = remote[id];
        const l = local[id];
        if (!l || (r.updatedAt || "") > (l.updatedAt || "")) merged[id] = r;
      }
      mapRef.current = merged;
      setMap(merged);
      writeAll(merged);
    }
    // Çıkışta yerel geçmişi TEMİZLE: paylaşılan cihazda sonraki kullanıcı önceki
    // kişinin sohbetlerini görmesin (veri sen kalır; girişte Supabase'ten geri gelir).
    function clearLocal() {
      syncId += 1; // uçuştaki sync'i geçersiz kıl
      mapRef.current = {};
      setMap({});
      try { localStorage.removeItem(KEY); } catch { /* özel mod */ }
    }
    sync();
    const off = onAuthChange((event) => {
      if (event === "SIGNED_OUT") clearLocal();
      else sync(); // SIGNED_IN → yeni oturumun geçmişini getir
    });
    return () => { cancelled = true; off(); };
  }, []);

  const list = sortedList(map);

  /** Sohbeti kaydet/güncelle (her tamamlanan turdan sonra). */
  const saveConversation = useCallback((id, { title, domain, turns, files }) => {
    if (!id || !(turns || []).length) return;
    const existing = mapRef.current[id] || {};
    const now = new Date().toISOString();
    const rec = {
      id,
      title: title || existing.title || (turns[0]?.question || "Sohbet").slice(0, 80),
      domain: domain || existing.domain || "",
      createdAt: existing.createdAt || now,
      updatedAt: now,
      turns,
      files: files || existing.files || [],
    };
    const next = { ...mapRef.current, [id]: rec };
    mapRef.current = next;
    setMap(next);
    writeAll(next);
    upsertConversationSb(id, { title: rec.title, domain: rec.domain, turns }); // misafirde no-op
  }, []);

  /** Sohbeti sil (yerel + backend). */
  const removeConversation = useCallback((id) => {
    if (!mapRef.current[id]) return;
    const next = { ...mapRef.current };
    delete next[id];
    mapRef.current = next;
    setMap(next);
    writeAll(next);
    deleteConversationSb(id); // misafirde no-op
  }, []);

  /** Bir sohbeti getir (turns ile) — yeniden yüklemek için. */
  const getConversation = useCallback((id) => map[id] || null, [map]);

  /** Tüm geçmişi sil ("tüm verilerimi sil") — yerel + Supabase (tek istek). */
  const clearAllConversations = useCallback(() => {
    mapRef.current = {};
    setMap({});
    try { localStorage.removeItem(KEY); } catch { /* yoksay */ }
    deleteAllConversationsSb(); // misafirde no-op
  }, []);

  /** "Sohbetlerde ara" / "Kaynaklar" / "Dosyalarım" — saf util'lere delege (test edilebilir). */
  const search = useCallback((q) => searchConversations(list, q), [list]);
  const allSources = useCallback(() => aggregateSources(list), [list]);
  const allFiles = useCallback(() => aggregateFiles(list), [list]);

  return {
    conversations: list, saveConversation, removeConversation, getConversation,
    clearAllConversations, search, allSources, allFiles,
  };
}
