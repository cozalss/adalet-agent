/* usePrefs (hook) — durumsal davranış: setPref/toggleDomain/clearAll +
   localStorage kalıcılığı + <html> data-attr uygulaması. Supabase senkronu
   mock'lanır (deterministik no-op): misafir davranışı = yalnız localStorage. */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

vi.mock("../lib/supabaseData.js", () => ({
  loadPrefsSb: vi.fn().mockResolvedValue(null),
  upsertPrefsSb: vi.fn().mockResolvedValue(false),
  clearPrefsSb: vi.fn().mockResolvedValue(false),
  onAuthChange: vi.fn(() => () => {}),
}));

import { usePrefs } from "./usePrefs.js";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-text-scale");
  document.documentElement.removeAttribute("data-reduce-motion");
});

describe("usePrefs (hook)", () => {
  it("setPref tercihi günceller + localStorage'a yazar + data-attr uygular", () => {
    const { result } = renderHook(() => usePrefs());
    act(() => result.current.setPref("textScale", "large"));
    expect(result.current.prefs.textScale).toBe("large");
    expect(JSON.parse(localStorage.getItem("adalet.prefs")).textScale).toBe("large");
    expect(document.documentElement.getAttribute("data-text-scale")).toBe("large");
  });

  it("reduceMotion → data-reduce-motion attribute'u eklenir", () => {
    const { result } = renderHook(() => usePrefs());
    act(() => result.current.setPref("reduceMotion", true));
    expect(document.documentElement.hasAttribute("data-reduce-motion")).toBe(true);
  });

  it("toggleDomain alanı açar, tekrar kapatır", () => {
    const { result } = renderHook(() => usePrefs());
    act(() => result.current.toggleDomain("kira"));
    expect(result.current.prefs.preferredDomains).toContain("kira");
    act(() => result.current.toggleDomain("kira"));
    expect(result.current.prefs.preferredDomains).not.toContain("kira");
  });

  it("clearAll varsayılana döner (saklanan değer de default'a sıfırlanır)", () => {
    const { result } = renderHook(() => usePrefs());
    act(() => result.current.setPref("textScale", "large"));
    act(() => result.current.clearAll());
    expect(result.current.prefs.textScale).toBe("normal");
    expect(result.current.prefs.displayName).toBe("");
    // removeItem sonrası prefs-değişim effect'i default'u geri yazar → veri yok demektir.
    expect(JSON.parse(localStorage.getItem("adalet.prefs")).textScale).toBe("normal");
  });
});
