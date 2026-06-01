/* ADALET kimlik durumu — e-posta/şifre giriş + misafir modu.

   Token localStorage("adalet-token")'da (api.js authHeaders bunu okur). Kullanıcı
   bilgisi JWT'den decode edilir (ekstra istek yok). "Misafir devam et" → anonim
   sohbet (mevcut davranış). Giriş/kayıt → token + kullanıcı; çıkış → temizle. */
import { useState, useCallback } from "react";
import { registerApi, loginApi } from "../lib/api.js";

const TOKEN_KEY = "adalet-token";
const GUEST_KEY = "adalet-guest";

/** JWT payload'ını decode et (imza DOĞRULAMAZ — yalnız görüntüleme; doğrulama backend'de). Test için export. */
export function decodeJwt(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    // TextDecoder ile güvenilir UTF-8 (escape/unescape deprecated + Türkçe char'da hatalı).
    const bytes = Uint8Array.from(atob(part), (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch { return null; }
}

/** Token → kullanıcı nesnesi (süresi dolmuşsa temizle + null). Test için export. */
export function userFromToken(token) {
  const c = token && decodeJwt(token);
  if (!c || !c.sub) return null;
  if (c.exp && c.exp * 1000 < Date.now()) {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* yoksay */ }
    return null;
  }
  return {
    sub: c.sub, role: c.role || "user",
    name: c.name || "", email: c.email || String(c.sub || "").replace(/^(user|beta):/, ""),
  };
}

export function useAuth() {
  const [token, setToken] = useState(() => {
    try { return localStorage.getItem(TOKEN_KEY) || null; } catch { return null; }
  });
  const [user, setUser] = useState(() => userFromToken(token));
  const [guest, setGuest] = useState(() => {
    try { return localStorage.getItem(GUEST_KEY) === "1"; } catch { return false; }
  });

  const authed = !!user;

  const _apply = useCallback((resp) => {
    try {
      localStorage.setItem(TOKEN_KEY, resp.access_token);
      localStorage.removeItem(GUEST_KEY);
    } catch { /* yoksay */ }
    setGuest(false);
    setToken(resp.access_token);
    setUser(userFromToken(resp.access_token));
  }, []);

  const login = useCallback(async (email, password) => {
    _apply(await loginApi({ email, password }));
  }, [_apply]);

  const register = useCallback(async (fields) => {
    _apply(await registerApi(fields));
  }, [_apply]);

  const continueAsGuest = useCallback(() => {
    try { localStorage.setItem(GUEST_KEY, "1"); } catch { /* yoksay */ }
    setGuest(true);
  }, []);

  const logout = useCallback(() => {
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(GUEST_KEY);
    } catch { /* yoksay */ }
    setToken(null); setUser(null); setGuest(false);
  }, []);

  return { token, user, authed, guest, login, register, continueAsGuest, logout };
}
