/* useChat (hook) — SSE durum-makinesinin fetch'siz davranışı:
   loadConversation / reset / undoReset / retryLast. (ask() fetch gerektirir → ayrı) */
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useChat } from "./useChat.js";

const conv = (id, questions) => ({
  id,
  turns: questions.map((q) => ({ question: q, phase: "final", data: { kind: "answer", domain: "kira" } })),
});

describe("useChat (hook)", () => {
  it("başlangıç: boş turns, busy=false, conversationId=null", () => {
    const { result } = renderHook(() => useChat());
    expect(result.current.turns).toEqual([]);
    expect(result.current.busy).toBe(false);
    expect(result.current.conversationId).toBeNull();
  });

  it("loadConversation geçmişi yükler (turns + taze key + conversationId, busy=false)", () => {
    const { result } = renderHook(() => useChat());
    act(() => result.current.loadConversation(conv("c1", ["soru bir"])));
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0].question).toBe("soru bir");
    expect(result.current.turns[0].key).toBeTypeOf("number");
    expect(result.current.conversationId).toBe("c1");
    expect(result.current.busy).toBe(false); // son turn 'final' → terminal
  });

  it("reset görünümü temizler (true); undoReset geri getirir", () => {
    const { result } = renderHook(() => useChat());
    act(() => result.current.loadConversation(conv("c1", ["soru"])));
    let ret;
    act(() => { ret = result.current.reset(); });
    expect(ret).toBe(true);
    expect(result.current.turns).toHaveLength(0);
    expect(result.current.conversationId).toBeNull();
    act(() => result.current.undoReset());
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.conversationId).toBe("c1");
  });

  it("boş sohbette reset false döner (undo gösterilmez)", () => {
    const { result } = renderHook(() => useChat());
    let ret;
    act(() => { ret = result.current.reset(); });
    expect(ret).toBe(false);
  });

  it("retryLast son soruyu döndürür + son turn'ü kaldırır", () => {
    const { result } = renderHook(() => useChat());
    act(() => result.current.loadConversation(conv("c1", ["q1", "q2"])));
    let q;
    act(() => { q = result.current.retryLast(); });
    expect(q).toBe("q2");
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0].question).toBe("q1");
  });
});
