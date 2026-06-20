/* ADALET hesap menüsü — sidebar kullanıcı pill'ine basınca açılan, ADALET'e ÖZGÜ
   menü (ChatGPT'nin "Plus / Planı yükselt" SaaS mantığı DEĞİL).

   Menü yukarı açılır (pill en altta). Öğeler şeffaflık + erişilebilirlik +
   açık kaynak kimliğini öne koyar. Her panel odak-tuzaklı modalde açılır. */
import React, { useState, useRef, useEffect, useCallback, useId } from "react";
import { Icon } from "./icons.jsx";
import { Avatar } from "./Avatar.jsx";
import {
  HowItWorksPanel, ScopePanel, SourcesPanel,
  PrefsPanel, DisclaimerPanel, OpenSourcePanel, ProfilePanel,
} from "./accountPanels.jsx";

// Menü grupları — her panel öğesi bir modal view'ı açar (ext yok, uydurma link yok).
const GROUPS = [
  {
    label: "Bu asistanı anla",
    items: [
      { id: "how", icon: "shield", label: "ADALET nasıl çalışır?" },
      { id: "scope", icon: "scale", label: "Hangi konularda yardımcı olurum?" },
      { id: "sources", icon: "book", label: "Kaynaklarım nereden geliyor?" },
    ],
  },
  {
    label: "Tercihler",
    items: [
      { id: "prefs", icon: "sliders", label: "Erişilebilirlik & tercihler" },
    ],
  },
  {
    label: "Güven",
    items: [
      { id: "disclaimer", icon: "help", label: "Sorumluluk reddi" },
      { id: "openSource", icon: "code", label: "Açık kaynak (MIT)" },
    ],
  },
];

const VIEW_TITLES = {
  how: "ADALET nasıl çalışır?",
  scope: "Hangi konularda yardımcı olurum?",
  sources: "Kaynaklarım nereden geliyor?",
  prefs: "Erişilebilirlik & tercihler",
  disclaimer: "Sorumluluk reddi",
  openSource: "Açık kaynak",
  profile: "Profili düzenle",
};
const WIDE_VIEWS = new Set(["how", "scope"]);

// Güven şeridi — ADALET'in kimlik farkları (uydurma değil; her rozet ilgili paneli açar).
// NOT: "Sıfır Uydurma" bilerek "how" panelini açar — sıfır-uydurma taahhüdü o panelin
// içindeki çekirdek-fark callout'udur (ayrı panel yok). stable `key` çeviri/yineleme güvenli.
const TRUST_BADGES = [
  { key: "agents", id: "how", icon: "users", label: "7 Ajan", title: "ADALET nasıl çalışır? — 7 ajanlı doğrulama ekibi" },
  { key: "nofab", id: "how", icon: "shield", label: "Sıfır Uydurma", title: "Her iddia kaynağıyla doğrulanır" },
  { key: "oss", id: "openSource", icon: "code", label: "Açık Kaynak", title: "MIT lisansı — kodu inceleyebilirsiniz" },
];

export function UserMenu({ prefs, setPref, toggleDomain, onClearSession, onAsk, showToast, user, onLogout }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(null);
  const rootRef = useRef(null);
  const btnRef = useRef(null);
  const menuRef = useRef(null);

  // Misafir modu yok → user her zaman var (App yalnız authed iken render edilir).
  const dispName = (user?.name || user?.email || prefs.displayName || "").trim();
  const shown = dispName || "Hesabım";
  const subtitle = user?.email || "Hesabım";

  // Menü dışına tıkla / Esc → kapat (modal açıkken modal kendi Esc'ini yönetir).
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape" && !view) { setOpen(false); btnRef.current?.focus(); } };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open, view]);

  // Menü açılınca odak ilk öğeye girsin (klavye/SR sözleşmesi — APG menu button).
  useEffect(() => {
    if (!open) return;
    const id = requestAnimationFrame(() => {
      menuRef.current?.querySelector('[role="menuitem"]')?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [open]);

  // Roving klavye gezinme — ↑/↓ döngüsel, Home/End; Tab menüden doğal çıkar.
  const onMenuKey = useCallback((e) => {
    const root = menuRef.current; if (!root) return;
    const items = Array.from(root.querySelectorAll('[role="menuitem"]:not([disabled])'));
    if (!items.length) return;
    const i = items.indexOf(document.activeElement);
    const focusAt = (n) => { e.preventDefault(); items[(n + items.length) % items.length].focus(); };
    if (e.key === "ArrowDown") focusAt(i + 1);
    else if (e.key === "ArrowUp") focusAt(i - 1);
    else if (e.key === "Home") focusAt(0);
    else if (e.key === "End") focusAt(items.length - 1);
  }, []);

  const openView = useCallback((id) => { setView(id); setOpen(false); }, []);
  const closeView = useCallback(() => setView(null), []);

  // ScopePanel örnek sorusu → modal+menü kapanır, app'e gönderilir.
  const askAndClose = useCallback((q) => { setView(null); setOpen(false); onAsk?.(q); }, [onAsk]);

  return (
    <div className="sb-user-wrap" ref={rootRef}>
      {open && (
        <div className="acc-menu" role="menu" aria-label="Hesap menüsü" ref={menuRef} onKeyDown={onMenuKey}>
          <button
            className="acc-id" role="menuitem" onClick={() => openView("profile")}
            aria-label={`${shown} — profili düzenle`}
          >
            <Avatar user={user} prefs={prefs} size={34} />
            <span className="acc-id-tx" aria-hidden="true">
              <b>{shown}</b>
              <span>{subtitle}</span>
            </span>
            <span className="acc-id-edit" aria-hidden="true"><Icon.pencil style={{ width: 14, height: 14 }} /></span>
          </button>
          <div className="acc-trust" role="group" aria-label="ADALET güven kimliği">
            {TRUST_BADGES.map((b, i) => {
              const I = Icon[b.icon] || Icon.shield;
              return (
                <button
                  className="acc-trust-badge" role="menuitem" key={b.key}
                  title={b.title} aria-label={b.label}
                  onClick={() => openView(b.id)}
                  style={i ? { animationDelay: `${0.04 * i}s` } : undefined}
                >
                  <span className="acc-trust-ic" aria-hidden="true"><I /></span>{b.label}
                </button>
              );
            })}
          </div>
          {GROUPS.map((g) => {
            const labelId = `acc-grp-${g.label.replace(/\s+/g, "-")}`;
            return (
              <div className="acc-group" key={g.label} role="group" aria-labelledby={labelId}>
                <div className="acc-group-label" id={labelId}>{g.label}</div>
                {g.items.map((it) => {
                  const I = Icon[it.icon] || Icon.info;
                  return (
                    <button className="acc-item" role="menuitem" key={it.id} onClick={() => openView(it.id)}>
                      <span className="acc-item-ic" aria-hidden="true"><I /></span>{it.label}
                    </button>
                  );
                })}
              </div>
            );
          })}
          <div className="acc-group" role="group" aria-label="Oturum yönetimi">
            <button className="acc-item" role="menuitem" onClick={() => { setOpen(false); onClearSession?.(); }}>
              <span className="acc-item-ic" aria-hidden="true"><Icon.refresh /></span>Bu oturumu temizle
            </button>
            <button className="acc-item danger-text" role="menuitem" onClick={() => { setOpen(false); onLogout?.(); }}>
              <span className="acc-item-ic" aria-hidden="true"><Icon.logout /></span>Oturumu kapat
            </button>
          </div>
          {/* footer — her yerde görünür hukuki uyarı (Avukatlık Kanunu yükümlülüğü) */}
          <div className="acc-foot" role="note">
            <Icon.scale aria-hidden="true" />
            <span>Yanıtlar bilgilendirme amaçlıdır, hukuki tavsiye değildir.</span>
          </div>
        </div>
      )}

      <button
        className={"sb-user" + (open ? " open" : "")} ref={btnRef}
        onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        aria-label="Hesap menüsünü aç"
      >
        <Avatar user={user} prefs={prefs} size={30} />
        <span className="who"><b>{shown}</b><span>Hesabım</span></span>
        <span className="grid-ic"><Icon.chevron style={{ transform: open ? "rotate(0)" : "rotate(180deg)" }} /></span>
      </button>

      {view && (
        <AccountModal title={VIEW_TITLES[view]} wide={WIDE_VIEWS.has(view)} onClose={closeView} returnFocus={btnRef}>
          {view === "how" && <HowItWorksPanel />}
          {view === "scope" && <ScopePanel onAsk={askAndClose} />}
          {view === "sources" && <SourcesPanel />}
          {view === "prefs" && <PrefsPanel prefs={prefs} setPref={setPref} toggleDomain={toggleDomain} />}
          {view === "disclaimer" && <DisclaimerPanel />}
          {view === "openSource" && <OpenSourcePanel />}
          {view === "profile" && (
            <ProfilePanel
              key={prefs.displayName}
              displayName={prefs.displayName}
              user={user}
              prefs={prefs}
              onSave={(n) => setPref("displayName", n)}
              onClose={closeView}
            />
          )}
        </AccountModal>
      )}
    </div>
  );
}

/* ---------- modal kabuğu (backdrop + odak tuzağı + Esc) ---------- */
function AccountModal({ title, children, onClose, wide, returnFocus }) {
  const ref = useRef(null);
  const titleId = useId();
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const SEL = 'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])';
    const focusables = () => Array.from(el.querySelectorAll(SEL)).filter((n) => !n.disabled && n.offsetParent !== null);
    focusables()[0]?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab") return;
      const f = focusables(); if (!f.length) return;
      const first = f[0], lastEl = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); returnFocus?.current?.focus?.(); };
  }, [onClose, returnFocus]);

  return (
    <div className="acc-modal-backdrop" onClick={onClose}>
      <div
        className={"acc-modal" + (wide ? " wide" : "")} ref={ref} role="dialog" aria-modal="true"
        aria-labelledby={titleId} onClick={(e) => e.stopPropagation()}
      >
        <div className="acc-modal-head">
          <h3 id={titleId}>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Kapat"><Icon.close /></button>
        </div>
        <div className="acc-modal-scroll">{children}</div>
      </div>
    </div>
  );
}
