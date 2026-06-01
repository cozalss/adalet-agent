/* ADALET sohbet geçmişi — localStorage birincil + backend senkron.

   ADALET artık sohbet geçmişi tutar. Birincil kaynak tarayıcı localStorage
   (anonim de dahil herkeste HEMEN çalışır); auth'lu kullanıcıda /me/conversations
   ile cihazlar-arası senkronlanır (best-effort, anonimde sessizce no-op).

   Türetilen: "Kaynaklar" (tüm sohbetlerdeki atıflar) ve "Dosyalarım" (yüklenen
   belge metadata'sı) bu kayıtlardan üretilir. */
import { useState, useCallback, useEffect, useRef } from "react";
import { putConversationApi, deleteConversationApi, deleteAllConversationsApi } from "../lib/api.js";
import {
  turnsToMessages, searchConversations, aggregateSources, aggregateFiles,
} from "../lib/conversationUtils.js";

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
    putConversationApi(id, { title: rec.title, domain: rec.domain, messages: turnsToMessages(turns) });
  }, []);

  /** Sohbeti sil (yerel + backend). */
  const removeConversation = useCallback((id) => {
    if (!mapRef.current[id]) return;
    const next = { ...mapRef.current };
    delete next[id];
    mapRef.current = next;
    setMap(next);
    writeAll(next);
    deleteConversationApi(id);
  }, []);

  /** Bir sohbeti getir (turns ile) — yeniden yüklemek için. */
  const getConversation = useCallback((id) => map[id] || null, [map]);

  /** Tüm geçmişi sil (KVKK "tüm verilerimi sil") — yerel + backend (tek istek). */
  const clearAllConversations = useCallback(() => {
    mapRef.current = {};
    setMap({});
    try { localStorage.removeItem(KEY); } catch { /* yoksay */ }
    deleteAllConversationsApi();
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
