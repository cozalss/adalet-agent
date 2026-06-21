/* ADALET kimlik durumu — Supabase Auth (e-posta/şifre + Google OAuth).

   Misafir modu KALDIRILDI: yalnız kayıt olup giriş yapan kullanıcılar siteye
   girebilir. Root, authed değilse her zaman AuthPage gösterir. Oturum supabase-js
   tarafından yönetilir (localStorage'da, otomatik yenilenir). Supabase
   yapılandırılmamışsa (env yok) giriş kullanılamaz (uygulama auth zorunlu). */
import { useState, useEffect, useCallback } from "react";
import { assertPasswordPolicyWithBreachCheck } from "../lib/passwordPolicy.js";
import { supabase, supabaseEnabled } from "../lib/supabase.js";

/** Supabase session → ADALET kullanıcı nesnesi. */
function userFromSession(session) {
  const u = session?.user;
  if (!u) return null;
  return {
    sub: u.id,
    email: u.email || "",
    name: u.user_metadata?.name || u.user_metadata?.full_name || "",
    role: "user",
  };
}

/** GoTrue hata mesajını Türkçe + kullanıcıya uygun hale getir. */
function mapAuthError(error) {
  const m = (error?.message || "").toLowerCase();
  if (m.includes("invalid login")) return "E-posta veya şifre hatalı.";
  if (m.includes("already registered") || m.includes("already been registered")) return "Bu e-posta zaten kayıtlı.";
  if (m.includes("at least") || m.includes("password")) return "Şifre yeterince güçlü değil.";
  if (m.includes("email")) return "Geçerli bir e-posta girin.";
  if (m.includes("provider is not enabled")) return "Google girişi bu projede henüz açık değil.";
  return error?.message || "Bir sorun oluştu, tekrar deneyin.";
}

export function useAuth() {
  const [user, setUser] = useState(null);
  // Supabase yoksa oturum sorgusu yok → hemen hazır. Varsa getSession bekler.
  const [ready, setReady] = useState(!supabaseEnabled);

  useEffect(() => {
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setUser(userFromSession(data.session));
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(userFromSession(session));
      setReady(true); // SIGNED_IN / OAuth redirect getSession'dan önce gelirse spinner takılmasın
    });
    return () => { active = false; sub.subscription.unsubscribe(); };
  }, []);

  const authed = !!user;

  const login = useCallback(async (email, password) => {
    if (!supabase) throw new Error("Giriş şu an kullanılamıyor (Supabase yapılandırılmadı).");
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(mapAuthError(error));
  }, []);

  /** Kayıt ol. E-posta onayı AÇIKSA oturum hemen oluşmaz → needsConfirmation:true
   *  döner (AuthPage "e-postanı doğrula" mesajı gösterir). KAPALIYSA SIGNED_IN
   *  olayı tetiklenir, kullanıcı otomatik içeri alınır. */
  const register = useCallback(async ({ email, password, name }) => {
    if (!supabase) throw new Error("Kayıt şu an kullanılamıyor (Supabase yapılandırılmadı).");
    await assertPasswordPolicyWithBreachCheck(password, { email, name });
    const { data, error } = await supabase.auth.signUp({
      email, password, options: { data: { name: name || "" } },
    });
    if (error) throw new Error(mapAuthError(error));
    return { needsConfirmation: !data?.session };
  }, []);

  const loginWithGoogle = useCallback(async () => {
    if (!supabase) throw new Error("Google girişi kullanılamıyor.");
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google", options: { redirectTo: window.location.origin },
    });
    if (error) throw new Error(mapAuthError(error));
  }, []);

  const logout = useCallback(async () => {
    if (supabase) { try { await supabase.auth.signOut(); } catch { /* yoksay */ } }
    setUser(null);
  }, []);

  return { user, authed, ready, login, register, loginWithGoogle, logout };
}
