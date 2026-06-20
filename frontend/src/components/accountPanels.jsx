/* ADALET hesap menüsü panelleri — ChatGPT kopyası DEĞİL, ADALET kimliği.

   Her panel ADALET'in farkını öne koyar: 7-ajan şeffaflık · sıfır-uydurma ·
   kapsam dürüstlüğü (ceza/aile yok) · erişilebilirlik · açık kaynak. Mevcut
   bileşen dili (at-timeline, line-icon, no-emoji) yeniden kullanılır. */
import React, { useState } from "react";
import { Icon, CIVIL_DOMAINS, OUT_OF_SCOPE } from "./icons.jsx";
import { Avatar } from "./Avatar.jsx";

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
  { name: "Mevzuat Bilgi Sistemi", host: "mevzuat.gov.tr", use: "Kanun & yönetmelik maddeleri", icon: "book" },
  { name: "Yargıtay Kararları", host: "yargitay.gov.tr", use: "Hukuk dairesi emsal kararları", icon: "scale" },
  { name: "Danıştay Kararları", host: "danistay.gov.tr", use: "İdari yargı içtihatları", icon: "scale" },
  { name: "Anayasa Mahkemesi", host: "anayasa.gov.tr", use: "Bireysel başvuru & norm denetimi", icon: "shield" },
  { name: "Resmî Gazete", host: "resmigazete.gov.tr", use: "Güncel mevzuat yayımı", icon: "file" },
];

export function SourcesPanel() {
  return (
    <div className="acc-body">
      <p className="acc-lead">
        Yanıtlar uydurma değildir; her referans aşağıdaki <b>kamuya açık resmî
        kaynaklardan</b> getirilir ve orijinaliyle eşleştirilir.
      </p>
      <ul className="acc-src-list">
        {SOURCES.map((s) => {
          const I = Icon[s.icon] || Icon.book;
          return (
            <li className="acc-src-item" key={s.host}>
              <span className="acc-src-ic"><I /></span>
              <div className="acc-src-tx">
                <span className="acc-src-name">{s.name}</span>
                <span className="acc-src-host">{s.host} · {s.use}</span>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="acc-callout">
        <span className="acc-callout-ic"><Icon.shield /></span>
        <div>
          Bir iddia bu kaynaklardan doğrulanamazsa <b>Doğrulama Ajanı cevabı
          reddeder</b> — uydurma madde veya karar üretilmez.
        </div>
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
const DISC_CAN = [
  "Mevzuat maddelerini ve emsal kararları bulup özetler",
  "Haklarınızı ve olası adımları sade dille açıklar",
  "Dilekçe taslağı hazırlamanıza yardımcı olur",
];
const DISC_CANNOT = [
  "Sizi mahkemede temsil edemez, vekâlet alamaz",
  "Kesin sonuç veya hukuki garanti veremez",
  "Avukat–müvekkil ilişkisi kurmaz",
];

export function DisclaimerPanel() {
  return (
    <div className="acc-body">
      <p className="acc-lead">ADALET bir <b>bilgilendirme aracıdır</b>, hukuki danışmanlık değildir.</p>

      {/* acc-priv-status/acc-priv-row yeniden kullanıldı: aynı success-soft tonu, bilinçli */}
      <div className="acc-priv-status">
        <div className="acc-sub-head" style={{ marginBottom: 2 }}>Yapabildiklerim</div>
        {DISC_CAN.map((t) => (
          <div className="acc-priv-row" key={t}><Icon.circleCheck />{t}</div>
        ))}
      </div>

      <div className="acc-scope-out" style={{ marginTop: 0 }}>
        <div className="acc-out-head"><Icon.close /> Yapamadıklarım</div>
        {DISC_CANNOT.map((t) => (
          <div className="acc-out-row" key={t}><b>{t}</b></div>
        ))}
      </div>

      <div className="acc-callout">
        <span className="acc-callout-ic"><Icon.scale /></span>
        <div>
          Bu sınır yasal bir zorunluluktur: hukuki danışmanlık ve mahkemede
          temsil yalnızca avukatlara tanınmıştır (<b>Avukatlık Kanunu</b>).
        </div>
      </div>

      <p className="acc-note">
        Yanıtlar gerçek mevzuat ve kararlara dayanır ancak hata içerebilir.
        Karmaşık, acil veya yüksek riskli durumlarda mutlaka bir avukata danışın.
        Her yanıtın altındaki kısa uyarı bu metnin özetidir.
      </p>
    </div>
  );
}

/* ---------- 7) Açık kaynak (MIT) ---------- */
const MIT_FREEDOMS = [
  { icon: "search", title: "İncele", desc: "Kodun tamamını satır satır okuyun." },
  { icon: "download", title: "Çalıştır", desc: "Kendi bilgisayarınızda kurup çalıştırın." },
  { icon: "pencil", title: "Değiştir", desc: "İhtiyacınıza göre uyarlayın." },
  { icon: "users", title: "Paylaş", desc: "Değişikliklerinizle birlikte dağıtın." },
];

export function OpenSourcePanel() {
  return (
    <div className="acc-body">
      <div className="acc-callout">
        <span className="acc-callout-ic"><Icon.code /></span>
        <div>
          ADALET <b>açık kaynaktır (MIT lisansı)</b>. “Sıfır uydurma” ve
          “kaynaklı yanıt” iddialarımızı kanıtlamanın tek dürüst yolu kodu
          herkese açmaktır.
        </div>
      </div>
      <div>
        <div className="acc-sub-head">MIT lisansı şunlara izin verir</div>
        <ul className="acc-src-list">
          {MIT_FREEDOMS.map((f) => {
            const I = Icon[f.icon] || Icon.check;
            return (
              <li className="acc-src-item" key={f.title}>
                <span className="acc-src-ic"><I /></span>
                <div className="acc-src-tx">
                  <span className="acc-src-name">{f.title}</span>
                  <span className="acc-src-host">{f.desc}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="acc-callout">
        <span className="acc-callout-ic"><Icon.shield /></span>
        <div>
          <b>Neden önemli?</b> Bir hukuk asistanına güvenmeniz için onu
          denetleyebilmeniz gerekir. Kapalı bir sistem “bana güvenin” der;
          açık kaynak <i>“kendiniz bakın”</i> der.
        </div>
      </div>
      <p className="acc-note">
        Kaynak kod deposu yayına hazırlanıyor; bitirme teslimiyle birlikte
        herkese açılacak. {/* repo URL henüz oluşturulmadı — uydurma link YOK */}
      </p>
    </div>
  );
}

/* ---------- 8) Profil (canlı avatar önizleme + görünen ad) ---------- */
export function ProfilePanel({ displayName, user, prefs, onSave, onClose }) {
  const [name, setName] = useState(displayName || "");
  const trimmed = name.trim();
  const dirty = trimmed !== (displayName || "").trim(); // değişiklik yoksa kayda gerek yok
  const save = () => { if (dirty) onSave?.(trimmed.slice(0, 60)); onClose?.(); };
  // Avatar canlı önizleme: yazılan ad önceliklenir → kullanıcı yazdıkça gem güncellenir.
  const previewName = trimmed || user?.name || user?.email || "";
  return (
    <div className="acc-body">
      <div className="acc-profile-preview">
        <Avatar user={{ name: previewName }} prefs={prefs} size={56} />
        <div className="acc-profile-id">
          <b>{trimmed || "Adınız burada görünür"}</b>
          {user?.email && <span>{user.email}</span>}
        </div>
      </div>
      <label className="acc-field">
        <span className="acc-field-label">Görünen ad</span>
        <input
          className="acc-input" value={name} maxLength={60} autoFocus
          placeholder="örn. Ayşe" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); }}
        />
        <span className="acc-field-counter" aria-hidden="true">{name.length}/60</span>
      </label>
      <p className="acc-note">
        Bu ad yalnız selamlamada görünür ve cihazınızda saklanır; kimseyle
        paylaşılmaz. İstemezseniz boş bırakın.
      </p>
      <div className="acc-confirm-actions" style={{ justifyContent: "flex-end" }}>
        <button className="acc-btn ghost" onClick={onClose}>Vazgeç</button>
        <button className="acc-btn primary" onClick={save} disabled={!dirty}>Kaydet</button>
      </div>
    </div>
  );
}
