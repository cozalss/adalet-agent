/* useAuth (hook) — Supabase Auth davranışı (supabase modülü mock'lanır, ağ yok). */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const { mockAuth } = vi.hoisted(() => ({
  mockAuth: {
    getSession: vi.fn(),
    onAuthStateChange: vi.fn(),
    signInWithPassword: vi.fn(),
    signUp: vi.fn(),
    signInWithOAuth: vi.fn(),
    signOut: vi.fn(),
  },
}));
vi.mock("../lib/supabase.js", () => ({ supabase: { auth: mockAuth }, supabaseEnabled: true }));

import { useAuth } from "./useAuth.js";

beforeEach(() => {
  localStorage.clear();
  mockAuth.getSession.mockResolvedValue({ data: { session: null } });
  mockAuth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  mockAuth.signInWithPassword.mockResolvedValue({ error: null });
  mockAuth.signUp.mockResolvedValue({ error: null });
  mockAuth.signInWithOAuth.mockResolvedValue({ error: null });
  mockAuth.signOut.mockResolvedValue({ error: null });
});

describe("useAuth (Supabase)", () => {
  it("oturum yokken: ready olur, authed=false, guest=false", async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.authed).toBe(false);
    expect(result.current.guest).toBe(false);
  });

  it("getSession bir kullanıcı dönerse authed=true + kullanıcı", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "u1", email: "a@b.com", user_metadata: { name: "Ayşe" } } } },
    });
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.authed).toBe(true));
    expect(result.current.user).toMatchObject({ sub: "u1", email: "a@b.com", name: "Ayşe" });
  });

  it("login → signInWithPassword çağırır + misafir bayrağı temizlenir", async () => {
    localStorage.setItem("adalet-guest", "1");
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => { await result.current.login("a@b.com", "Gizli123"); });
    expect(mockAuth.signInWithPassword).toHaveBeenCalledWith({ email: "a@b.com", password: "Gizli123" });
    expect(localStorage.getItem("adalet-guest")).toBeNull();
  });

  it("login hatası Türkçe mesaja çevrilir", async () => {
    mockAuth.signInWithPassword.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.ready).toBe(true));
    await expect(result.current.login("a@b.com", "yanlis")).rejects.toThrow("E-posta veya şifre hatalı");
  });

  it("register → signUp'ı name metadata'sıyla çağırır", async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => { await result.current.register({ email: "x@y.com", password: "Gizli123", name: "Veli" }); });
    expect(mockAuth.signUp).toHaveBeenCalledWith({
      email: "x@y.com", password: "Gizli123", options: { data: { name: "Veli" } },
    });
  });

  it("continueAsGuest → guest=true; logout → signOut çağırır", async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.continueAsGuest());
    expect(result.current.guest).toBe(true);
    await act(async () => { await result.current.logout(); });
    expect(mockAuth.signOut).toHaveBeenCalled();
    expect(result.current.guest).toBe(false);
  });
});
