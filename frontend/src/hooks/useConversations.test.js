/* useConversations (hook) — kaydet/listele/getir/ara/sil durumsal davranışı +
   localStorage kalıcılığı. Supabase senkronu mock'lanır (deterministik no-op):
   misafir davranışı = yalnız localStorage. */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

vi.mock("../lib/supabaseData.js", () => ({
  loadConversationsSb: vi.fn().mockResolvedValue(null),
  upsertConversationSb: vi.fn().mockResolvedValue(false),
  deleteConversationSb: vi.fn().mockResolvedValue(false),
  deleteAllConversationsSb: vi.fn().mockResolvedValue(false),
  onAuthChange: vi.fn(() => () => {}),
}));

import { useConversations } from "./useConversations.js";

const turn = (q, a) => ({
  question: q, phase: "final",
  data: { domain: "kira", answer: { text: a, confidence: 80 }, sources: [] },
});

beforeEach(() => localStorage.clear());

describe("useConversations (hook)", () => {
  it("saveConversation listeye ekler + localStorage'a yazar", () => {
    const { result } = renderHook(() => useConversations());
    act(() => result.current.saveConversation("c1", { title: "Kira", domain: "kira", turns: [turn("soru", "cevap")] }));
    expect(result.current.conversations).toHaveLength(1);
    expect(result.current.conversations[0].title).toBe("Kira");
    expect(JSON.parse(localStorage.getItem("adalet.conversations")).c1.title).toBe("Kira");
  });

  it("turns'siz çağrı yok sayılır", () => {
    const { result } = renderHook(() => useConversations());
    act(() => result.current.saveConversation("c1", { title: "X", turns: [] }));
    expect(result.current.conversations).toHaveLength(0);
  });

  it("getConversation turn'lerle döner; search içerikte filtreler", () => {
    const { result } = renderHook(() => useConversations());
    act(() => {
      result.current.saveConversation("c1", { title: "Kira artışı", turns: [turn("zam", "tüfe sınırı")] });
      result.current.saveConversation("c2", { title: "İş", turns: [turn("kıdem", "30 gün")] });
    });
    expect(result.current.getConversation("c1").turns).toHaveLength(1);
    expect(result.current.search("kıdem").map((c) => c.id)).toEqual(["c2"]);
    expect(result.current.search("").length).toBe(2);
  });

  it("removeConversation tek kaydı siler", () => {
    const { result } = renderHook(() => useConversations());
    act(() => result.current.saveConversation("c1", { title: "X", turns: [turn("q", "a")] }));
    act(() => result.current.removeConversation("c1"));
    expect(result.current.conversations).toHaveLength(0);
  });

  it("clearAllConversations tümünü siler + localStorage temizlenir", () => {
    const { result } = renderHook(() => useConversations());
    act(() => {
      result.current.saveConversation("c1", { title: "X", turns: [turn("q", "a")] });
      result.current.saveConversation("c2", { title: "Y", turns: [turn("q", "a")] });
    });
    act(() => result.current.clearAllConversations());
    expect(result.current.conversations).toHaveLength(0);
    expect(localStorage.getItem("adalet.conversations")).toBeNull();
  });
});
