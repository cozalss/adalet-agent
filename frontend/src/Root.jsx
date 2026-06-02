/* ADALET kök yönlendirici — giriş kapısı.
   Auth yoksa AuthPage (giriş/kayıt); YALNIZ giriş yapınca /sor sohbet uygulaması
   (misafir modu YOK — site kayıt/giriş zorunlu). ?preview=1 auth'u atlar (tasarım QA). */
import React from "react";
import { useAuth } from "./hooks/useAuth.js";
import { AuthPage } from "./pages/AuthPage.jsx";
import App from "./App.jsx";
import "./styles/auth.css";

const hasParam = (k) => typeof window !== "undefined" && new URLSearchParams(window.location.search).has(k);

// ?preview=1 auth kapısını ATLAR → yalnız DEV'de (production'da bypass YASAK). Demo turn de gösterir.
const PREVIEW = import.meta.env.DEV && hasParam("preview");
// ?e2e=1 auth'u ATLAR (demo turn YOK — App normal çalışır) → YALNIZ VITE_E2E=1 ile derlenmişse
// (Playwright build). Gerçek prod (Vercel) VITE_E2E set ETMEZ → bu bypass üretimde kapalıdır.
// Güvenlik (MEDIUM): VITE_E2E build yanlışlıkla staging/preview'e yüklenirse ?e2e=1 prod
// host'ta auth ATLAMASIN — runtime hostname guard ile yalnız localhost'ta geçerli (Playwright localhost).
const isLocalHost =
  typeof window !== "undefined" &&
  /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);
const E2E_BYPASS = import.meta.env.VITE_E2E === "1" && hasParam("e2e") && isLocalHost;
const SKIP_AUTH = PREVIEW || E2E_BYPASS;

export function Root() {
  const auth = useAuth();
  // Supabase oturumu yüklenirken (ready=false) login sayfası flash etmesin.
  if (!SKIP_AUTH && !auth.ready) {
    return <div className="auth-page" data-theme="warm" style={{ display: "grid", placeItems: "center" }}><span className="auth-spin" /></div>;
  }
  if (!SKIP_AUTH && !auth.authed) {
    return (
      <AuthPage
        onLogin={auth.login}
        onRegister={auth.register}
        onGoogle={auth.loginWithGoogle}
      />
    );
  }
  return <App auth={auth} />;
}
