/* ADALET giriş / kayıt sayfası — editorial split-screen (uiwjs/react-login-page
   UX desenleri: logo bloğu + alanlar + submit + tab; ADALET kimliğine özgün
   uyarlandı, kütüphane KURULMADI). Giriş/kayıt → /sor sohbet sayfasına geçilir. */
import React, { useState } from "react";
import { Icon } from "../components/icons.jsx";
import { passwordPolicyIssues } from "../lib/passwordPolicy.js";
import { supabaseEnabled } from "../lib/supabase.js";
import { ShimmerButton } from "../components/ui/shimmer-button.jsx";

const TRUST = [
  { icon: "shield", t: "Yargıtay kararları ve mevzuatla doğrulanır" },
  { icon: "book", t: "Her yanıtın kaynağı açık ve izlenebilir" },
  { icon: "check", t: "Sıfır uydurma taahhüdü" },
];

export function AuthPage({ onLogin, onRegister, onGoogle }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(""); // başarı/bilgi (örn. e-posta doğrula)
  const [loading, setLoading] = useState(false);

  const isReg = mode === "register";

  const switchMode = (m) => { setMode(m); setError(""); setNotice(""); };

  const google = async () => {
    setError("");
    try { await onGoogle?.(); } catch (err) { setError(err?.message || "Google girişi başarısız."); }
  };

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setNotice("");
    if (!email.trim() || !password) { setError("E-posta ve şifre gerekli."); return; }
    if (isReg && !consent) { setError("Devam etmek için gizlilik onayı gerekli."); return; }
    if (isReg) {
      const issues = passwordPolicyIssues(password, { email: email.trim(), name: name.trim() });
      if (issues.length) { setError(issues[0]); return; }
    }
    setLoading(true);
    try {
      if (isReg) {
        const res = await onRegister({ email: email.trim(), password, name: name.trim() });
        // E-posta onayı açıksa oturum oluşmaz → kullanıcıya yönlendir (boşta kalmasın).
        // Onay kapalıysa SIGNED_IN otomatik içeri alır (Root yönlendirir).
        if (res?.needsConfirmation) {
          setMode("login");
          setPassword(""); // login denemesinde 'onayla' + 'şifre hatalı' çelişkisi olmasın
          setNotice("Hesabın oluşturuldu. E-postana gönderilen onay bağlantısına tıkla, sonra giriş yap.");
        }
      } else {
        await onLogin(email.trim(), password);
      }
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
          {!supabaseEnabled && (
            <div className="auth-error" role="alert" style={{ marginBottom: 18 }}>
              <Icon.info />Giriş servisi yapılandırılmadı (VITE_SUPABASE_* eksik). Lütfen yöneticiye bildirin.
            </div>
          )}
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

          {notice && <div className="auth-notice" role="status"><Icon.check />{notice}</div>}

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
            <ShimmerButton
              type="submit"
              disabled={loading || !supabaseEnabled}
              background="var(--accent)"
              shimmerColor="#f1dcbb"
              shimmerDuration="3.6s"
              borderRadius="12px"
              className="w-full h-12 mt-1.5 text-[15px] font-semibold disabled:opacity-70 disabled:cursor-default"
            >
              {loading ? <span className="auth-spin" aria-hidden="true" /> : (isReg ? "Hesap oluştur" : "Giriş yap")}
            </ShimmerButton>
          </form>

          <div className="auth-divider"><span>veya</span></div>
          {onGoogle && (
            <button type="button" className="auth-google" onClick={google} disabled={!supabaseEnabled}>
              <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden="true">
                <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8a12 12 0 1 1 7.9-21l5.7-5.7A20 20 0 1 0 24 44c11 0 20-9 20-20 0-1.3-.1-2.3-.4-3.5z" />
                <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8A12 12 0 0 1 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7A20 20 0 0 0 6.3 14.7z" />
                <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2A12 12 0 0 1 12.7 28l-6.6 5.1A20 20 0 0 0 24 44z" />
                <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3a12 12 0 0 1-4.1 5.6l6.2 5.2C39.9 39 44 34 44 24c0-1.3-.1-2.3-.4-3.5z" />
              </svg>
              Google ile devam et
            </button>
          )}
          <p className="auth-disclaimer">ADALET hukuki danışmanlık değildir; bilgilendirme amaçlıdır.</p>
        </div>
      </main>
    </div>
  );
}
