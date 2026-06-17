/* ADALET sohbet geçmişi — saf veri dönüşümleri (hook'tan ayrı, test edilebilir).

   useConversations bu fonksiyonları kullanır; React/localStorage'a bağımlı
   olmadıkları için doğrudan birim test edilebilirler (Kaynaklar/Dosyalarım/arama
   ve backend mesaj dönüşümü mantığı). */

import { parseSections } from "./parseAnswer.js";

/** Cevap metnini turn'den çıkar (answer.text veya reject body). */
export function answerText(turn) {
  const d = (turn && turn.data) || {};
  if (d.answer?.text) return d.answer.text;
  if (d.reject?.body) return d.reject.body;
  return "";
}

/** Yerel turn dizisini backend mesaj şemasına çevir (user + assistant satırları). */
export function turnsToMessages(turns) {
  const msgs = [];
  (turns || []).forEach((t, i) => {
    msgs.push({ turn_index: i * 2, role: "user", content: t.question || "", domain: t.data?.domain || "" });
    const ans = answerText(t);
    if (ans) {
      msgs.push({
        turn_index: i * 2 + 1, role: "assistant", content: ans, domain: t.data?.domain || "",
        // Zengin atıf: source_id + snippet + tür → reload'da sections/çip/panel yeniden kurulur
        // (yoksa eski kayıtlar 'Cevap' başlığı + ham [src:] olarak bozuk görünüyordu).
        citations: (t.data?.sources || []).map((s) => ({
          id: s.id, source_id: s.ref, title: s.title, badge: s.badge, type: s.type,
          snippet: s.passage, url: s.url,
        })),
        confidence: t.data?.answer?.confidence || 0,
      });
    }
  });
  return msgs;
}

/** DB mesaj dizisini görüntülenebilir turn dizisine çevir (turnsToMessages tersi).
 *
 *  Tam turn 'data' şekli (fazlar, ara durumlar) localStorage'da yaşar; bu yeniden
 *  kurulum CİHAZLAR-ARASI geçmişi GÖSTERMEK için yeterli minimumdur: soru + cevap
 *  metni + atıflar + güven. domain konuşma seviyesinde tutulur (mesajda kolon yok). */
export function messagesToTurns(messages, domain = "") {
  const sorted = [...(messages || [])].sort((a, b) => (a.turn_index ?? 0) - (b.turn_index ?? 0));
  const turns = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const m = sorted[i];
    if (m.role !== "user") continue;
    const next = sorted[i + 1];
    const ans = next && next.role === "assistant" ? next : null;
    // Kaynak kartlarını DB atıflarından geri kur (panel + çip için ref/snippet dahil).
    const sources = (ans?.citations || []).map((c, idx) => ({
      id: c.id ?? idx + 1,
      type: c.type || (c.doc_type === "law" ? "Kanun" : "Yargıtay"),
      badge: c.badge || (c.doc_type === "law" ? "kanun" : "yargitay"),
      title: c.title || c.source_id || "",
      ref: c.source_id || "",
      passage: c.snippet || "",
      url: c.url || "",
      verified: true,
      rel: [c.id ?? idx + 1],
    }));
    // source_id → çip numarası (kaydedilmişse). Eski kayıtlarda ref yoksa → [src:] STRIP edilir
    // (ham etiket görünmez), düzgün sections korunur.
    const citeMap = new Map(sources.filter((s) => s.ref).map((s) => [s.ref, s.id]));
    const text = ans?.content || "";
    // KRİTİK FİX: metni yeniden parse et → 'Cevap' başlığı + ham [src:] yerine düzgün
    // bölümler + çipler (oturum-içi yeni mesajlarla AYNI görünüm).
    const sections = text ? parseSections(text, citeMap) : [];
    turns.push({
      question: m.content || "",
      phase: "final",
      data: {
        kind: "answer",
        domain,
        answer: { text, confidence: Number(ans?.confidence) || 0, sections },
        sources,
        sourceCount: sources.length,
      },
    });
  }
  return turns;
}

const SEARCH_FOLD = {
  ç: "c", ğ: "g", ı: "i", i: "i", ö: "o", ş: "s", ü: "u",
};

export function normalizeSearchText(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase("tr-TR")
    .replace(/[çğıiöşü]/g, (ch) => SEARCH_FOLD[ch] || ch)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function editDistance(a, b) {
  if (a === b) return 0;
  if (!a) return b.length;
  if (!b) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const cur = [i];
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
    }
    prev = cur;
  }
  return prev[b.length];
}

function closeToken(queryToken, hayToken) {
  if (queryToken === hayToken || hayToken.includes(queryToken)) return true;
  if (/\d/.test(queryToken) || /\d/.test(hayToken)) return false;
  if (queryToken.length < 5 || hayToken.length < 5) return false;
  const maxDistance = queryToken.length >= 9 ? 2 : 1;
  if (queryToken[0] !== hayToken[0] && maxDistance <= 1) return false;
  return editDistance(queryToken, hayToken) <= maxDistance;
}

function fuzzyIncludes(hay, needle) {
  if (hay.includes(needle)) return true;
  const hayTokens = hay.split(/\s+/).filter(Boolean);
  const queryTokens = needle.split(/\s+/).filter(Boolean);
  if (!queryTokens.length) return true;
  return queryTokens.every((qt) => hayTokens.some((ht) => closeToken(qt, ht)));
}

/** "Sohbetlerde ara" — başlık + soru + cevap metninde (TR case-fold). Boş q → tümü. */
export function searchConversations(list, q) {
  const ql = normalizeSearchText(q);
  if (!ql) return list || [];
  return (list || []).filter((c) => {
    const hay = [c.title, ...(c.turns || []).flatMap((t) => [t.question, answerText(t)])]
      .join(" ");
    return fuzzyIncludes(normalizeSearchText(hay), ql);
  });
}

/** "Kaynaklar" — tüm sohbetlerdeki atıfları birleştir (doc_type:title ile tekille). */
export function aggregateSources(list) {
  const seen = new Map();
  (list || []).forEach((c) => (c.turns || []).forEach((t) => (t.data?.sources || []).forEach((s) => {
    const k = `${s.doc_type || ""}:${s.title || s.id}`;
    if (!seen.has(k)) seen.set(k, { ...s, convId: c.id, convTitle: c.title });
  })));
  return [...seen.values()];
}

/** "Dosyalarım" — tüm sohbetlerdeki yüklenen belgeleri birleştir. */
export function aggregateFiles(list) {
  const out = [];
  (list || []).forEach((c) => (c.files || []).forEach((f) => out.push({ ...f, convId: c.id, convTitle: c.title })));
  return out;
}
