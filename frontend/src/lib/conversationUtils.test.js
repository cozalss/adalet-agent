/* conversationUtils — sohbet geçmişi saf mantığı (arama/toplama/dönüşüm) testleri. */
import { describe, it, expect } from "vitest";
import {
  answerText, turnsToMessages, messagesToTurns,
  searchConversations, aggregateSources, aggregateFiles, normalizeSearchText,
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
  const srcCard = {
    id: 1, type: "Kanun", badge: "kanun", title: "TBK m.344",
    ref: "m-TBK-344", passage: "madde metni", url: "http://x",
  };

  it("her tur için user + (varsa) assistant satırı üretir", () => {
    const msgs = turnsToMessages([turn("soru", "yanıt", [srcCard], 88)]);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]).toMatchObject({ turn_index: 0, role: "user", content: "soru" });
    expect(msgs[1]).toMatchObject({ turn_index: 1, role: "assistant", content: "yanıt", confidence: 88 });
    // Zengin atıf: source_id + snippet saklanır (reload'da sections/çip/panel için)
    expect(msgs[1].citations).toEqual([{
      id: 1, source_id: "m-TBK-344", title: "TBK m.344", badge: "kanun",
      type: "Kanun", snippet: "madde metni", url: "http://x",
    }]);
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

describe("messagesToTurns", () => {
  const srcCard = {
    id: 1, type: "Kanun", badge: "kanun", title: "TBK m.344",
    ref: "m-TBK-344", passage: "madde metni", url: "http://x",
  };

  it("DB mesajlarından görüntülenebilir turn'leri kurar + sections YENİDEN PARSE eder", () => {
    const body = "**Kısa cevap:** Yasal sınır budur [src: m-TBK-344].";
    const msgs = turnsToMessages([turn("soru", body, [srcCard], 88)]);
    const turns = messagesToTurns(msgs, "kira");
    expect(turns).toHaveLength(1);
    expect(turns[0]).toMatchObject({ question: "soru", phase: "final" });
    expect(turns[0].data).toMatchObject({ kind: "answer", domain: "kira", sourceCount: 1 });
    expect(turns[0].data.answer.confidence).toBe(88);
    // KRİTİK FİX: reload'da sections yeniden kurulur (ham-text fallback DEĞİL)
    expect(turns[0].data.answer.sections.length).toBeGreaterThan(0);
    // ham [src:] etiketi render'a sızmamalı (textToRuns strip + çip)
    expect(JSON.stringify(turns[0].data.answer.sections)).not.toContain("src:");
    // kaynak kartı ref/snippet ile geri kurulur (panel için)
    expect(turns[0].data.sources[0]).toMatchObject({ id: 1, ref: "m-TBK-344", title: "TBK m.344", passage: "madde metni" });
  });

  it("turn_index sırasız gelse de doğru eşler + sıralar", () => {
    const msgs = [
      { turn_index: 1, role: "assistant", content: "a1", citations: [], confidence: 70 },
      { turn_index: 0, role: "user", content: "s1" },
      { turn_index: 2, role: "user", content: "s2" },
    ];
    const turns = messagesToTurns(msgs, "isHukuku");
    expect(turns.map((t) => t.question)).toEqual(["s1", "s2"]);
    expect(turns[0].data.answer.text).toBe("a1");
    expect(turns[1].data.answer.text).toBe(""); // s2'nin cevabı yok
  });

  it("boş/undefined girdi → []", () => {
    expect(messagesToTurns(undefined)).toEqual([]);
    expect(messagesToTurns([])).toEqual([]);
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
  it("Türkçe diakritik olmadan arar", () => {
    expect(searchConversations(list, "tufe").map((c) => c.id)).toEqual(["a"]);
    expect(searchConversations(list, "kidem").map((c) => c.id)).toEqual(["b"]);
  });
  it("küçük yazım hatasını tolere eder", () => {
    expect(searchConversations(list, "tazmnatı").map((c) => c.id)).toEqual(["b"]);
  });
  it("eşleşme yoksa []", () => {
    expect(searchConversations(list, "trafik")).toEqual([]);
  });
  it("sayılarda fuzzy eşleştirme yapmaz", () => {
    expect(searchConversations(list, "31")).toEqual([]);
  });
  it("null liste → []", () => {
    expect(searchConversations(null, "x")).toEqual([]);
  });
});

describe("normalizeSearchText", () => {
  it("TR case + diakritik fold uygular", () => {
    expect(normalizeSearchText("İŞÇİ TÜFE")).toBe("isci tufe");
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
