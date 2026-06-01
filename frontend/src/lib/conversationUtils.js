/* ADALET sohbet geçmişi — saf veri dönüşümleri (hook'tan ayrı, test edilebilir).

   useConversations bu fonksiyonları kullanır; React/localStorage'a bağımlı
   olmadıkları için doğrudan birim test edilebilirler (Kaynaklar/Dosyalarım/arama
   ve backend mesaj dönüşümü mantığı). */

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
        citations: (t.data?.sources || []).map((s) => ({ id: s.id, title: s.title, doc_type: s.doc_type })),
        confidence: t.data?.answer?.confidence || 0,
      });
    }
  });
  return msgs;
}

/** "Sohbetlerde ara" — başlık + soru + cevap metninde (TR case-fold). Boş q → tümü. */
export function searchConversations(list, q) {
  const ql = (q || "").trim().toLocaleLowerCase("tr-TR");
  if (!ql) return list || [];
  return (list || []).filter((c) => {
    const hay = [c.title, ...(c.turns || []).flatMap((t) => [t.question, answerText(t)])]
      .join(" ").toLocaleLowerCase("tr-TR");
    return hay.includes(ql);
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
