/* ADALET giriş / kayıt sayfası — editorial split-screen (uiwjs/react-login-page
   UX desenleri: logo bloğu + alanlar + submit + tab; ADALET kimliğine özgün
   uyarlandı, kütüphane KURULMADI). Giriş/kayıt → /sor sohbet sayfasına geçilir. */
import React, { useState } from "react";
import { Icon } from "../components/icons.jsx";

const TRUST = [
  { icon: "shield", t: "Yargıtay kararları ve mevzuatla doğrulanır" },
  { icon: "book", t: "Her yanıtın kaynağı açık ve izlenebilir" },
  { icon: "check", t: "Sıfır uydurma taahhüdü" },
];

export function AuthPage({ onLogin, onRegister, onGuest }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const isReg = mode === "register";

  const switchMode = (m) => { setMode(m); setError(""); };

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!email.trim() || !password) { setError("E-posta ve şifre gerekli."); return; }
    if (isReg && password.length < 8) { setError("Şifre en az 8 karakter olmalı."); return; }
    if (isReg && !consent) { setError("Devam etmek için gizlilik onayı gerekli."); return; }
    setLoading(true);
    try {
      if (isReg) await onRegister({ email: email.trim(), password, name: name.trim(), privacy_consent: consent });
      else await onLogin(email.trim(), password);
    } catch (err) {
      setError(err?.message || "Bir sorun oluştu, lütfen tekrar deneyin.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page" data-theme="warm">
      <aside className="auth-brand">
        <div className="auth-brand-inner">
          <div className="auth-logo"><span className="auth-logo-mark"><Icon.scale /></span>ADALET</div>
          <h1 className="auth-tagline">Türkçe hukuk için <em>doğrulanmış</em> yapay zekâ asistanı</h1>
          <ul className="auth-trust">
            {TRUST.map((x) => {
              const I = Icon[x.icon];
              return <li key={x.t}><span className="auth-trust-ic"><I /></span>{x.t}</li>;
            })}
          </ul>
          <p className="auth-brand-foot">Avukat tutamayanların hak arama aracı · Açık kaynak (MIT)</p>
        </div>
      </aside>

      <main className="auth-form-wrap">
        <div className="auth-card">
          <div className="auth-tabs" role="tablist" aria-label="Giriş veya kayıt">
            <button id="tab-login" role="tab" aria-selected={!isReg} aria-controls="auth-panel"
              className={!isReg ? "on" : ""} onClick={() => switchMode("login")}>Giriş</button>
            <button id="tab-register" role="tab" aria-selected={isReg} aria-controls="auth-panel"
              className={isReg ? "on" : ""} onClick={() => switchMode("register")}>Kayıt ol</button>
          </div>

          <h2 className="auth-title">{isReg ? "Hesap oluşturun" : "Tekrar hoş geldiniz"}</h2>
          <p className="auth-sub">{isReg
            ? "Sohbet geçmişiniz hesabınıza kaydedilsin, her cihazdan erişin."
            : "Sohbet geçmişinize erişmek için giriş yapın."}</p>

          <form className="auth-form" onSubmit={submit} noValidate
            role="tabpanel" id="auth-panel" aria-labelledby={isReg ? "tab-register" : "tab-login"}>
            {isReg && (
              <label className="auth-field">
                <span>Ad <small>(opsiyonel)</small></span>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80}
                  placeholder="örn. Ayşe" autoComplete="name" />
              </label>
            )}
            <label className="auth-field">
              <span>E-posta</span>
              <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" inputMode="email"
                placeholder="ornek@eposta.com" autoComplete="email" maxLength={120} autoFocus />
            </label>
            <label className="auth-field">
              <span>Şifre</span>
              <div className="auth-pw">
                <input value={password} onChange={(e) => setPassword(e.target.value)}
                  type={showPw ? "text" : "password"} placeholder={isReg ? "en az 8 karakter" : "••••••••"}
                  autoComplete={isReg ? "new-password" : "current-password"} maxLength={128} />
                <button type="button" className="auth-pw-toggle" onClick={() => setShowPw((v) => !v)}
                  aria-label={showPw ? "Şifreyi gizle" : "Şifreyi göster"}>{showPw ? "gizle" : "göster"}</button>
              </div>
            </label>
            {isReg && (
              <label className="auth-consent">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>Gizlilik ve veri işleme bilgilendirmesini okudum, onaylıyorum.</span>
              </label>
            )}
            {error && <div className="auth-error" role="alert"><Icon.info />{error}</div>}
            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? <span className="auth-spin" aria-hidden="true" /> : (isReg ? "Hesap oluştur" : "Giriş yap")}
            </button>
          </form>

          <div className="auth-divider"><span>veya</span></div>
          <button className="auth-guest" onClick={onGuest}>Misafir olarak devam et</button>
          <p className="auth-disclaimer">ADALET hukuki danışmanlık değildir; bilgilendirme amaçlıdır.</p>
        </div>
      </main>
    </div>
  );
}
