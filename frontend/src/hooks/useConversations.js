/* ADALET sohbet geçmişi — localStorage birincil + backend senkron.

   ADALET artık sohbet geçmişi tutar. Birincil kaynak tarayıcı localStorage
   (anonim de dahil herkeste HEMEN çalışır); auth'lu kullanıcıda /me/conversations
   ile cihazlar-arası senkronlanır (best-effort, anonimde sessizce no-op).

   Türetilen: "Kaynaklar" (tüm sohbetlerdeki atıflar) ve "Dosyalarım" (yüklenen
   belge metadata'sı) bu kayıtlardan üretilir. */
import { useState, useCallback, useEffect, useRef } from "react";
import { putConversationApi, deleteConversationApi, deleteAllConversationsApi } from "../lib/api.js";

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

/** Cevap metnini turn'den çıkar (answer.text veya reject body). */
function answerText(turn) {
  const d = turn.data || {};
  if (d.answer?.text) return d.answer.text;
  if (d.reject?.body) return d.reject.body;
  return "";
}

/** Yerel turn dizisini backend mesaj şemasına çevir (user+assistant satırları). */
function turnsToMessages(turns) {
  const msgs = [];
  (turns || []).forEach((t, i) => {
    msgs.push({ turn_index: i * 2, role: "user", content: t.question || "", domain: t.data?.domain || "" });
    const ans = answerText(t);
    if (ans) {
      msgs.push({
        turn_index: i * 2 + 1, role: "assistant", content: ans, domain: t.data?.domain || "",
        citations: (t.data?.sources || []).map((s) => ({ id: s.id, title: s.title, doc_type: s.doc_type })),
        confidence: t.data?.answer?.confidence || 0,
      });
    }
  });
  return msgs;
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

  /** "Sohbetlerde ara" — başlık + soru + cevap metninde ara. */
  const search = useCallback((q) => {
    const ql = (q || "").trim().toLocaleLowerCase("tr-TR");
    if (!ql) return list;
    return list.filter((c) => {
      const hay = [c.title, ...(c.turns || []).flatMap((t) => [t.question, answerText(t)])]
        .join(" ").toLocaleLowerCase("tr-TR");
      return hay.includes(ql);
    });
  }, [list]);

  /** "Kaynaklar" — tüm sohbetlerdeki atıfları birleştir (kaynak id'ye göre tekille). */
  const allSources = useCallback(() => {
    const seen = new Map();
    list.forEach((c) => (c.turns || []).forEach((t) => (t.data?.sources || []).forEach((s) => {
      const k = `${s.doc_type || ""}:${s.title || s.id}`;
      if (!seen.has(k)) seen.set(k, { ...s, convId: c.id, convTitle: c.title });
    })));
    return [...seen.values()];
  }, [list]);

  /** "Dosyalarım" — tüm sohbetlerdeki yüklenen belgeleri birleştir. */
  const allFiles = useCallback(() => {
    const out = [];
    list.forEach((c) => (c.files || []).forEach((f) => out.push({ ...f, convId: c.id, convTitle: c.title })));
    return out;
  }, [list]);

  return {
    conversations: list, saveConversation, removeConversation, getConversation,
    clearAllConversations, search, allSources, allFiles,
  };
}
