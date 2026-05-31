/* ADALET hesap menüsü panelleri — ChatGPT kopyası DEĞİL, ADALET kimliği.

   Her panel ADALET'in farkını öne koyar: 7-ajan şeffaflık · sıfır-uydurma ·
   KVKK lokal-veri · kapsam dürüstlüğü (ceza/aile yok) · erişilebilirlik · açık
   kaynak. Mevcut bileşen dili (at-timeline, line-icon, no-emoji) yeniden kullanılır. */
import React, { useState } from "react";
import { Icon, CIVIL_DOMAINS, OUT_OF_SCOPE } from "./icons.jsx";

/* ---------- 1) ADALET nasıl çalışır? (7-ajan + sıfır uydurma) ---------- */
const AGENTS = [
  { name: "Triaj Ajanı", icon: "tag", desc: "Sorunuzu 8 hukuk alanından birine yerleştirir." },
  { name: "Mevzuat Ajanı", icon: "book", desc: "İlgili kanun maddelerini mevzuat.gov.tr'den çeker." },
  { name: "Emsal Ajanı", icon: "search", desc: "Yargıtay'dan benzer kararları bulur." },
  { name: "Dilekçe Ajanı", icon: "pencil", desc: "İsterseniz resmi dilekçe taslağı hazırlar." },
  { name: "Doğrulama Ajanı", icon: "shield", desc: "Her iddiayı orijinal kaynakla karşılaştırır.", star: true },
  { name: "Tartışma Ajanı", icon: "users", desc: "Ajan görüşlerini tartar, hakemlik yapar." },
  { name: "Tahmin Ajanı", icon: "scale", desc: "Geçmiş kararlara göre olası sonucu tahmin eder." },
];

export function HowItWorksPanel() {
  return (
    <div className="acc-body">
      <p className="acc-lead">
        ADALET tek bir yapay zekâ değil; her biri farklı iş yapan <b>yedi ajandan</b>
        oluşan bir ekiptir. Cevap üretmeden önce her iddia kaynağıyla doğrulanır.
      </p>
      <ol className="acc-agents" aria-label="Ajan ekibi">
        {AGENTS.map((a) => {
          const I = Icon[a.icon] || Icon.check;
          return (
            <li className={"acc-agent" + (a.star ? " star" : "")} key={a.name}>
              <span className="acc-agent-ic"><I /></span>
              <div className="acc-agent-tx">
                <span className="acc-agent-name">{a.name}{a.star && <span className="acc-star">çekirdek fark</span>}</span>
                <span className="acc-agent-desc">{a.desc}</span>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="acc-callout">
        <span className="acc-callout-ic"><Icon.shield /></span>
        <div>
          <b>Sıfır uydurma taahhüdü.</b> Bir iddia orijinal kaynaktan
          doğrulanamazsa cevap reddedilir, ajan en fazla 3 kez yeniden dener.
          Emin olunamazsa ADALET açıkça <i>“bu konuda emin değilim, bir avukata
          danışın”</i> der. Hiçbir madde numarası veya karar uydurulmaz.
        </div>
      </div>
      <p className="acc-note">
        Her cevapta gördüğünüz <b>%güven</b>, <b>kaynak sayısı</b> ve
        <b> doğrulanan iddia</b> rozetleri bu sürecin özetidir.
      </p>
    </div>
  );
}

/* ---------- 2) Hangi konularda yardımcı olurum? (kapsam + dürüst sınır) ---------- */
export function ScopePanel({ onAsk }) {
  return (
    <div className="acc-body">
      <p className="acc-lead">
        ADALET <b>8 sivil hukuk alanında</b> yardımcı olur. Bir örneğe dokunarak
        hemen sorabilirsiniz.
      </p>
      <div className="acc-scope-grid">
        {CIVIL_DOMAINS.map((d) => {
          const I = Icon[d.icon] || Icon.scale;
          return (
            <button className="acc-scope-card" key={d.id} onClick={() => onAsk?.(d.ex)} title={d.ex}>
              <span className="acc-scope-ic"><I /></span>
              <span className="acc-scope-label">{d.label}</span>
              <span className="acc-scope-ex">{d.ex}</span>
            </button>
          );
        })}
      </div>
      <div className="acc-scope-out">
        <div className="acc-out-head"><Icon.close /> Bilerek kapsam dışı</div>
        {OUT_OF_SCOPE.map((o) => (
          <div className="acc-out-row" key={o.label}>
            <b>{o.label}</b><span>{o.why}</span>
          </div>
        ))}
        <p className="acc-out-foot">Bu konularda sizi doğrudan bir avukata yönlendiririz.</p>
      </div>
    </div>
  );
}

/* ---------- 3) Kaynaklarım nereden geliyor? ---------- */
const SOURCES = [
  { name: "Mevzuat Bilgi Sistemi", host: "mevzuat.gov.tr", use: "Kanun maddeleri" },
  { name: "Yargıtay Kararları", host: "yargitay.gov.tr", use: "Emsal kararlar" },
  { name: "Resmi Gazete", host: "resmigazete.gov.tr", use: "Güncel mevzuat" },
  { name: "Danıştay", host: "danistay.gov.tr", use: "İdari hukuk" },
];

export function SourcesPanel() {
  return (
    <div className="acc-body">
      <p className="acc-lead">
        Yanıtlar uydurma değildir; her referans aşağıdaki <b>kamuya açık resmî
        kaynaklardan</b> getirilir ve orijinaliyle eşleştirilir.
      </p>
      <ul className="acc-src-list">
        {SOURCES.map((s) => (
          <li className="acc-src-item" key={s.host}>
            <span className="acc-src-ic"><Icon.book /></span>
            <div className="acc-src-tx">
              <span className="acc-src-name">{s.name}</span>
              <span className="acc-src-host">{s.host} · {s.use}</span>
            </div>
          </li>
        ))}
      </ul>
      <p className="acc-note">
        Bir iddia bu kaynaklardan doğrulanamazsa Doğrulama Ajanı cevabı reddeder.
      </p>
    </div>
  );
}

/* ---------- 4) Gizlilik & verilerim (KVKK panosu) ---------- */
const PRIVACY_FACTS = [
  "Sohbet geçmişiniz kaydedilir — istediğiniz an silebilirsiniz.",
  "Misafir kullanımda geçmiş bu cihazda (tarayıcı) tutulur.",
  "Belgelerinizdeki TC / telefon / IBAN otomatik maskelenir.",
  "Yapay zekâ modelleri yerel çalışır — yanıtlar Türkiye'de işlenir.",
];

export function PrivacyPanel({ onClearData }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="acc-body">
      <div className="acc-priv-status">
        {PRIVACY_FACTS.map((f) => (
          <div className="acc-priv-row" key={f}><Icon.check /><span>{f}</span></div>
        ))}
      </div>
      <div className="acc-priv-stored">
        <div className="acc-sub-head">Neler saklanıyor</div>
        <p>• Sohbet geçmişiniz (başlık + sorular + yanıtlar)</p>
        <p>• Tercihleriniz (yazı boyutu, hareket, alanlar)</p>
        <p className="acc-note">Hepsini aşağıdaki butonla kalıcı silebilirsiniz.</p>
      </div>
      <div className="acc-danger-zone">
        {!confirm ? (
          <button className="acc-btn danger-ghost" onClick={() => setConfirm(true)}>
            <Icon.lock /> Tüm yerel verilerimi sil
          </button>
        ) : (
          <div className="acc-confirm">
            <span>Tercihleriniz ve oturum verileriniz kalıcı silinecek. Emin misiniz?</span>
            <div className="acc-confirm-actions">
              <button className="acc-btn ghost" onClick={() => setConfirm(false)}>Vazgeç</button>
              <button className="acc-btn danger" onClick={() => { onClearData?.(); setConfirm(false); }}>
                Evet, hepsini sil
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- 5) Erişilebilirlik & tercihler ---------- */
function Toggle({ checked, onChange, label }) {
  return (
    <button
      className={"acc-toggle" + (checked ? " on" : "")} role="switch" aria-checked={checked}
      onClick={() => onChange(!checked)}
    >
      <span className="acc-toggle-label">{label}</span>
      <span className="acc-toggle-track" aria-hidden="true"><span className="acc-toggle-knob" /></span>
    </button>
  );
}

const SCALES = [
  { id: "compact", label: "A", size: 13 },
  { id: "normal", label: "A", size: 16 },
  { id: "large", label: "A", size: 20 },
];

export function PrefsPanel({ prefs, setPref, toggleDomain }) {
  return (
    <div className="acc-body">
      <div className="acc-pref-group">
        <div className="acc-sub-head">Yazı boyutu</div>
        <div className="acc-scale" role="group" aria-label="Yazı boyutu">
          {SCALES.map((s) => (
            <button
              key={s.id}
              className={"acc-scale-btn" + (prefs.textScale === s.id ? " on" : "")}
              style={{ fontSize: s.size }} aria-pressed={prefs.textScale === s.id}
              onClick={() => setPref("textScale", s.id)}
            >{s.label}</button>
          ))}
        </div>
      </div>
      <div className="acc-pref-group">
        <Toggle checked={prefs.reduceMotion} onChange={(v) => setPref("reduceMotion", v)} label="Hareketi azalt" />
        <Toggle checked={prefs.highContrast} onChange={(v) => setPref("highContrast", v)} label="Yüksek kontrast" />
      </div>
      <div className="acc-pref-group">
        <div className="acc-sub-head">Tercih edilen alanlar</div>
        <p className="acc-note" style={{ marginTop: 0 }}>Seçtiğiniz alanlar boş ekranda öne çıkar (boş = hepsi).</p>
        <div className="acc-chips">
          {CIVIL_DOMAINS.map((d) => {
            const on = prefs.preferredDomains.includes(d.id);
            const I = Icon[d.icon] || Icon.scale;
            return (
              <button
                key={d.id} className={"acc-chip" + (on ? " on" : "")} aria-pressed={on}
                onClick={() => toggleDomain(d.id)}
              ><I />{d.label}</button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ---------- 6) Sorumluluk reddi ---------- */
export function DisclaimerPanel() {
  return (
    <div className="acc-body">
      <p className="acc-lead">ADALET bir <b>bilgilendirme aracıdır</b>, hukuki danışmanlık değildir.</p>
      <ul className="acc-disc-list">
        <li>Yanıtlar gerçek mevzuat ve kararlara dayanır, ancak hata içerebilir.</li>
        <li>Karmaşık veya acil durumlarda mutlaka bir avukata danışın.</li>
        <li>ADALET sizi mahkemede temsil edemez, vekâlet alamaz (Avukatlık Kanunu).</li>
      </ul>
      <p className="acc-note">Her yanıtın altındaki kısa uyarı bu metnin özetidir.</p>
    </div>
  );
}

/* ---------- 7) Açık kaynak (MIT) ---------- */
export function OpenSourcePanel() {
  return (
    <div className="acc-body">
      <div className="acc-callout">
        <span className="acc-callout-ic"><Icon.code /></span>
        <div>
          ADALET <b>açık kaynaktır (MIT lisansı)</b>. Şeffaflık iddiamızı
          kanıtlarız: kodun tamamını inceleyebilir, kendiniz çalıştırabilirsiniz.
        </div>
      </div>
      <p className="acc-note">
        Kaynak kod deposu yayına hazırlanıyor; bitirme teslimiyle birlikte
        herkese açılacak. {/* repo URL henüz oluşturulmadı — uydurma link YOK */}
      </p>
    </div>
  );
}

/* ---------- 8) Profil (KVKK-minimal: tek alan) ---------- */
export function ProfilePanel({ displayName, onSave, onClose }) {
  const [name, setName] = useState(displayName || "");
  const save = () => { onSave?.(name.trim().slice(0, 60)); onClose?.(); };
  return (
    <div className="acc-body">
      <label className="acc-field">
        <span className="acc-field-label">Görünen ad</span>
        <input
          className="acc-input" value={name} maxLength={60} autoFocus
          placeholder="örn. Ayşe" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); }}
        />
      </label>
      <p className="acc-note">
        Bu ad yalnız selamlamada görünür ve cihazınızda saklanır; kimseyle
        paylaşılmaz. İstemezseniz boş bırakın.
      </p>
      <div className="acc-confirm-actions" style={{ justifyContent: "flex-end" }}>
        <button className="acc-btn ghost" onClick={onClose}>Vazgeç</button>
        <button className="acc-btn primary" onClick={save}>Kaydet</button>
      </div>
    </div>
  );
}
