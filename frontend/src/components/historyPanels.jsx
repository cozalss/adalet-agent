/* ADALET sidebar nav panelleri — Sohbetlerde ara · Kaynaklar · Dosyalarım.
   Hepsi sohbet geçmişinden (useConversations) türetilir. */
import React, { useState, useMemo } from "react";
import { Icon } from "./icons.jsx";

/** ISO tarih → kısa Türkçe ("bugün" / "dün" / "12 May"). Mutasyonsuz (Date.UTC). */
export function relDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = new Date();
  const d0 = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const n0 = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.floor((n0 - d0) / 86400000);
  if (days <= 0) return "bugün";
  if (days === 1) return "dün";
  if (days < 7) return `${days} gün önce`;
  return d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

/* ---------- Sohbetlerde ara ---------- */
export function SearchPanel({ search, onSelect }) {
  const [q, setQ] = useState("");
  const results = useMemo(() => search(q), [q, search]);
  return (
    <div className="acc-body">
      <div className="hp-search-box">
        <Icon.search />
        <input
          className="hp-search-input" value={q} autoFocus placeholder="Geçmiş sohbetlerde ara…"
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {results.length === 0 ? (
        <p className="acc-note">{q ? "Eşleşen sohbet yok." : "Henüz sohbet yok."}</p>
      ) : (
        <div className="hp-list">
          {results.map((c) => (
            <button className="hp-row" key={c.id} onClick={() => onSelect(c)}>
              <span className="hp-row-ic"><Icon.book /></span>
              <span className="hp-row-tx">
                <span className="hp-row-title">{c.title}</span>
                <span className="hp-row-meta">{c.domain || "sohbet"} · {relDate(c.updatedAt)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Kaynaklar (tüm sohbetlerdeki atıflar) ---------- */
const DOC_LABEL = { law: "Kanun", case: "Yargıtay" };

export function LibraryPanel({ sources, onSelect }) {
  if (!sources.length) {
    return (
      <div className="acc-body">
        <div className="hp-empty">
          <Icon.book />
          <p>Sohbetlerinizde atıf yapılan kanun maddeleri ve mahkeme kararları burada birikir.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="acc-body">
      <p className="acc-note">{sources.length} kaynak · {sources.length} sohbetten</p>
      <div className="hp-list">
        {sources.map((s, i) => (
          <button className="hp-src" key={`${s.doc_type || ""}:${s.title || s.id}:${i}`} onClick={() => onSelect?.(s.convId)} title={s.convTitle}>
            <span className={"hp-src-tag " + (s.doc_type === "case" ? "case" : "law")}>
              {DOC_LABEL[s.doc_type] || "Kaynak"}
            </span>
            <span className="hp-src-tx">
              <span className="hp-src-title">{s.title}</span>
              {s.convTitle && <span className="hp-src-meta">{s.convTitle}</span>}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------- Dosyalarım (yüklenen belgeler) ---------- */
export function FilesPanel({ files, onSelect }) {
  if (!files.length) {
    return (
      <div className="acc-body">
        <div className="hp-empty">
          <Icon.image />
          <p>Soru sorarken yüklediğiniz belgeler (OCR) burada listelenir. Gizlilik için yalnız belge bilgisi tutulur, metin değil.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="acc-body">
      <p className="acc-note">{files.length} belge</p>
      <div className="hp-list">
        {files.map((f, i) => (
          <button className="hp-file" key={`${f.filename || "f"}:${f.convId || ""}:${i}`} onClick={() => onSelect?.(f.convId)} title={f.convTitle}>
            <span className="hp-file-ic"><Icon.image /></span>
            <span className="hp-file-tx">
              <span className="hp-file-name">{f.filename || "belge"}</span>
              <span className="hp-file-meta">
                {(f.n_chars || 0).toLocaleString("tr-TR")} karakter
                {f.pii && <span className="hp-pii">● kişisel veri</span>}
                {f.convTitle && ` · ${f.convTitle}`}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
