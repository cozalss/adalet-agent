/* conversationUtils — sohbet geçmişi saf mantığı (arama/toplama/dönüşüm) testleri. */
import { describe, it, expect } from "vitest";
import {
  answerText, turnsToMessages, searchConversations, aggregateSources, aggregateFiles,
} from "./conversationUtils.js";

const turn = (q, ans, sources, conf) => ({
  question: q,
  data: { domain: "kira", answer: ans ? { text: ans, confidence: conf } : undefined, sources },
});

describe("answerText", () => {
  it("answer.text döner", () => {
    expect(answerText({ data: { answer: { text: "cevap" } } })).toBe("cevap");
  });
  it("answer yoksa reject.body döner", () => {
    expect(answerText({ data: { reject: { body: "red" } } })).toBe("red");
  });
  it("hiçbiri yoksa boş", () => {
    expect(answerText({ data: {} })).toBe("");
    expect(answerText({})).toBe("");
  });
});

describe("turnsToMessages", () => {
  it("her tur için user + (varsa) assistant satırı üretir", () => {
    const msgs = turnsToMessages([turn("soru", "yanıt", [{ id: 1, title: "TBK m.344", doc_type: "law" }], 88)]);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]).toMatchObject({ turn_index: 0, role: "user", content: "soru" });
    expect(msgs[1]).toMatchObject({ turn_index: 1, role: "assistant", content: "yanıt", confidence: 88 });
    expect(msgs[1].citations).toEqual([{ id: 1, title: "TBK m.344", doc_type: "law" }]);
  });

  it("cevap yoksa yalnız user satırı", () => {
    const msgs = turnsToMessages([turn("soru", null)]);
    expect(msgs).toHaveLength(1);
    expect(msgs[0].role).toBe("user");
  });

  it("turn_index çift/tek artar (çok turlu)", () => {
    const msgs = turnsToMessages([turn("s1", "a1"), turn("s2", "a2")]);
    expect(msgs.map((m) => m.turn_index)).toEqual([0, 1, 2, 3]);
  });

  it("boş/undefined girdi → []", () => {
    expect(turnsToMessages(undefined)).toEqual([]);
    expect(turnsToMessages([])).toEqual([]);
  });
});

describe("searchConversations", () => {
  const list = [
    { id: "a", title: "Kira artışı", turns: [turn("ev sahibi zam", "TÜFE sınırı")] },
    { id: "b", title: "İşten çıkarılma", turns: [turn("kıdem tazminatı", "30 günlük ücret")] },
  ];
  it("boş q → tüm liste", () => {
    expect(searchConversations(list, "")).toBe(list);
    expect(searchConversations(list, "  ")).toBe(list);
  });
  it("başlıkta arar", () => {
    expect(searchConversations(list, "kira").map((c) => c.id)).toEqual(["a"]);
  });
  it("soru metninde arar", () => {
    expect(searchConversations(list, "kıdem").map((c) => c.id)).toEqual(["b"]);
  });
  it("cevap metninde arar", () => {
    expect(searchConversations(list, "tüfe").map((c) => c.id)).toEqual(["a"]);
  });
  it("eşleşme yoksa []", () => {
    expect(searchConversations(list, "trafik")).toEqual([]);
  });
  it("null liste → []", () => {
    expect(searchConversations(null, "x")).toEqual([]);
  });
});

describe("aggregateSources", () => {
  it("tüm sohbetlerden birleştirir, doc_type:title ile tekiller", () => {
    const list = [
      { id: "a", title: "A", turns: [turn("q", "ans", [{ id: 1, title: "TBK m.344", doc_type: "law" }])] },
      { id: "b", title: "B", turns: [turn("q", "ans", [{ id: 2, title: "TBK m.344", doc_type: "law" }])] }, // dup
      { id: "c", title: "C", turns: [turn("q", "ans", [{ id: 3, title: "Yargıtay 9.HD", doc_type: "case" }])] },
    ];
    const out = aggregateSources(list);
    expect(out).toHaveLength(2); // dup elendi
    expect(out[0]).toMatchObject({ title: "TBK m.344", convId: "a", convTitle: "A" });
    expect(out[1]).toMatchObject({ title: "Yargıtay 9.HD", convId: "c" });
  });
  it("kaynak yoksa boş", () => {
    expect(aggregateSources([{ id: "a", title: "A", turns: [turn("q", "ans")] }])).toEqual([]);
    expect(aggregateSources(null)).toEqual([]);
  });
});

describe("aggregateFiles", () => {
  it("tüm sohbetlerin dosyalarını düzleştirir + conv bilgisi ekler", () => {
    const list = [
      { id: "a", title: "A", files: [{ filename: "x.pdf" }, { filename: "y.png" }] },
      { id: "b", title: "B", files: [{ filename: "z.pdf" }] },
    ];
    const out = aggregateFiles(list);
    expect(out).toHaveLength(3);
    expect(out[0]).toMatchObject({ filename: "x.pdf", convId: "a", convTitle: "A" });
    expect(out[2]).toMatchObject({ filename: "z.pdf", convId: "b" });
  });
  it("dosya yoksa boş", () => {
    expect(aggregateFiles([{ id: "a", files: [] }])).toEqual([]);
    expect(aggregateFiles(null)).toEqual([]);
  });
});
