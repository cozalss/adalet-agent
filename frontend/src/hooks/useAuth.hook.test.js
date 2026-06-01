/* useAuth (hook) — misafir/çıkış durumsal davranışı + token'dan başlangıç. */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAuth } from "./useAuth.js";

beforeEach(() => localStorage.clear());

function makeToken(payload) {
  const b64url = (o) => {
    const bytes = new TextEncoder().encode(JSON.stringify(o));
    let bin = ""; for (const b of bytes) bin += String.fromCharCode(b);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };
  return `${b64url({ alg: "HS256" })}.${b64url(payload)}.sig`;
}

describe("useAuth (hook)", () => {
  it("token + guest yokken authed=false, guest=false", () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.authed).toBe(false);
    expect(result.current.guest).toBe(false);
  });

  it("geçerli token localStorage'da → authed=true + kullanıcı", () => {
    const exp = Math.floor(Date.now() / 1000) + 3600;
    localStorage.setItem("adalet-token", makeToken({ sub: "user:a@b.com", name: "Ali", exp }));
    const { result } = renderHook(() => useAuth());
    expect(result.current.authed).toBe(true);
    expect(result.current.user.name).toBe("Ali");
  });

  it("continueAsGuest → guest=true + localStorage işareti", () => {
    const { result } = renderHook(() => useAuth());
    act(() => result.current.continueAsGuest());
    expect(result.current.guest).toBe(true);
    expect(localStorage.getItem("adalet-guest")).toBe("1");
  });

  it("logout → token + guest temizlenir, authed=false", () => {
    const exp = Math.floor(Date.now() / 1000) + 3600;
    localStorage.setItem("adalet-token", makeToken({ sub: "user:a@b.com", exp }));
    localStorage.setItem("adalet-guest", "1");
    const { result } = renderHook(() => useAuth());
    act(() => result.current.logout());
    expect(result.current.authed).toBe(false);
    expect(localStorage.getItem("adalet-token")).toBeNull();
    expect(localStorage.getItem("adalet-guest")).toBeNull();
  });
});
