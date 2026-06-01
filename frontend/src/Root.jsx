/* ADALET kök yönlendirici — giriş kapısı.
   Auth yoksa AuthPage (giriş/kayıt); giriş yapılınca veya misafir seçilince /sor
   sohbet uygulaması. ?preview=1 auth'u atlar (tasarım QA). */
import React from "react";
import { useAuth } from "./hooks/useAuth.js";
import { AuthPage } from "./pages/AuthPage.jsx";
import App from "./App.jsx";
import "./styles/auth.css";

// ?preview=1 auth kapısını ATLAR → yalnız DEV'de (production'da bypass YASAK).
const PREVIEW = import.meta.env.DEV
  && typeof window !== "undefined" && new URLSearchParams(window.location.search).has("preview");

export function Root() {
  const auth = useAuth();
  // Supabase oturumu yüklenirken (ready=false) login sayfası flash etmesin.
  if (!PREVIEW && !auth.ready) {
    return <div className="auth-page" data-theme="warm" style={{ display: "grid", placeItems: "center" }}><span className="auth-spin" /></div>;
  }
  if (!PREVIEW && !auth.authed && !auth.guest) {
    return (
      <AuthPage
        onLogin={auth.login}
        onRegister={auth.register}
        onGoogle={auth.loginWithGoogle}
        onGuest={auth.continueAsGuest}
      />
    );
  }
  return <App auth={auth} />;
}
