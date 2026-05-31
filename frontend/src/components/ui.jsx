/* ADALET /sor — paylaşılan UI bileşenleri (stepper, citation, kaynak kartı, güven).
   Prototipten birebir; Icon ES import. */
import React, { useState, useRef, useEffect } from "react";
import { Icon } from "./icons.jsx";

const STEP_LABELS = {
  triage: "Sorunuz sınıflandırılıyor…",
  sources: "Kaynaklar aranıyor: kanun + Yargıtay",
  drafting: "Cevap hazırlanıyor…",
  final: "Doğrulanıyor…",
};
export const STEP_ORDER = ["triage", "sources", "drafting", "final"];

export function StreamStepper({ phase, customLabel }) {
  const idx = STEP_ORDER.indexOf(phase);
  const pct = ((idx + 1) / 4) * 100;
  const label = customLabel && idx === 0 ? customLabel : STEP_LABELS[phase];
  return (
    <div
      className="card stream-card"
      role="progressbar"
      aria-valuemin={0} aria-valuemax={4} aria-valuenow={idx + 1}
      aria-valuetext={label}
    >
      <div className="stream-progress"><span style={{ width: pct + "%" }}></span></div>
      <div className="stepper">
        {STEP_ORDER.map((s, i) => {
          const cls = i < idx ? "done" : i === idx ? "active" : "";
          return (
            <div className={"step " + cls} key={s} aria-current={i === idx ? "step" : undefined}>
              <div className="node">{i < idx ? <Icon.check /> : i + 1}</div>
              {i < 3 && <div className="line"></div>}
            </div>
          );
        })}
      </div>
      <div className="stepper-label">
        <span className="pulse"></span>
        {label}
      </div>
    </div>
  );
}

export function CitationMarker({ n, source, onJump }) {
  const [open, setOpen] = useState(false);
  return (
    <span style={{ position: "relative" }}>
      <span
        className="cite" tabIndex={0} role="button"
        aria-label={"Kaynak " + n + (source ? ": " + source.title : "")}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => onJump && onJump(n, e.currentTarget)}
      >
        {n}
      </span>
      {open && source && (
        <span className="cite-pop" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
          <span className="t mono">{source.badge === "kanun" ? "KANUN" : source.type.toUpperCase()} · {source.ref}</span>
          <span className="ttl">{source.title}</span>
          <span className="ex">{source.passage.slice(0, 96)}…</span>
          <span className="cite-go">
            <span className="v">
              <Icon.check />
              {source.verified ? "Kaynaktan doğrulandı" : "Kaynak"}
              {source.url ? " · " + source.url.replace(/^https?:\/\//, "").split("/")[0] : ""}
            </span>
            <span className="go">Kaynağa git →</span>
          </span>
        </span>
      )}
    </span>
  );
}

export function RunText({ runs, sources, onJump }) {
  return (
    <React.Fragment>
      {runs.map((r, i) => {
        if (r.cite != null) {
          const src = sources.find((s) => s.id === r.cite);
          return <CitationMarker key={i} n={r.cite} source={src} onJump={onJump} />;
        }
        return <React.Fragment key={i}>{r.t}</React.Fragment>;
      })}
    </React.Fragment>
  );
}

export function ConfidenceBar({ value, count }) {
  const [w, setW] = useState(0);
  useEffect(() => { const id = setTimeout(() => setW(value), 80); return () => clearTimeout(id); }, [value]);
  const mid = value < 70;
  return (
    <div className={"card confidence" + (mid ? " mid" : "")} style={{ marginTop: 14 }}>
      <span className="label">Güven</span>
      <span className="track"><span className="fill" style={{ width: w + "%" }}></span></span>
      <span className="pct mono">%{value}</span>
      <span className="verified"><Icon.check /> {count} kaynakla {mid ? "kısmen " : ""}doğrulandı</span>
    </div>
  );
}

export function Badge({ type, badge }) {
  return <span className={"badge " + badge}>{badge === "kanun" && <Icon.book style={{ width: 12, height: 12 }} />}{type}</span>;
}

export function RiskWarning({ html }) {
  return (
    <div className="risk">
      <span className="r-ic"><Icon.clock /></span>
      <span className="r-tx" dangerouslySetInnerHTML={{ __html: html }}></span>
    </div>
  );
}

const DISCLAIMER_FALLBACK =
  "Bu yanıt genel bilgilendirme amaçlıdır, hukuki danışmanlık veya avukatlık " +
  "hizmeti yerine geçmez. Somut durumunuz için bir avukata başvurun.";

/** Backend cevaba özel disclaimer(ler) verdiyse onları göster; yoksa statik
 *  fallback. `items`: string[] (örn. çocuk filtresi, süre uyarısı). */
export function DisclaimerBar({ items }) {
  const list = Array.isArray(items) && items.length ? items : [DISCLAIMER_FALLBACK];
  return (
    <div className="disclaimer">
      <Icon.info />
      <span>{list.join(" ")}</span>
    </div>
  );
}

export function SourceCard({ s, flash, onRef }) {
  const ref = useRef(null);
  const onMove = (e) => {
    const el = ref.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.setProperty("--mx", px * 100 + "%");
    el.style.setProperty("--my", py * 100 + "%");
    el.style.setProperty("--rx", (px - 0.5) * 7 + "deg");
    el.style.setProperty("--ry", (0.5 - py) * 7 + "deg");
  };
  const onLeave = () => {
    const el = ref.current; if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };
  return (
    <div
      className={"card src-card" + (flash ? " flash" : "")}
      id={"src-" + s.id}
      ref={(el) => { ref.current = el; if (onRef) onRef(el); }}
      data-src-id={s.id}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
    >
      <div className="sc-head">
        <span className={"sc-seal " + s.badge} aria-hidden="true">
          {s.badge === "kanun" ? <Icon.book /> : <Icon.scale />}
        </span>
        <Badge type={s.type} badge={s.badge} />
        <span className="sc-title">{s.title}</span>
        {s.verified && <span className="sc-verify"><Icon.check /> Doğrulandı</span>}
      </div>
      <div className="sc-passage">
        <span className="mono mono-ref" style={{ color: "var(--text-3)", fontSize: 11, display: "block", marginBottom: 4 }}>{s.ref}</span>
        “{s.passage}”
      </div>
      <div className="sc-foot">
        {s.url ? (
          <a href={s.url.startsWith("http") ? s.url : "https://" + s.url} target="_blank" rel="noreferrer">
            {s.url.replace(/^https?:\/\//, "")} <Icon.ext />
          </a>
        ) : <span />}
        {s.rel && s.rel.length > 0 && (
          <span className="rel">İlgili: {s.rel.map((r) => <span className="cite" key={r}>{r}</span>)}</span>
        )}
      </div>
    </div>
  );
}

export function SourceSkeleton() {
  return (
    <div className="card src-skeleton">
      <div className="skl" style={{ height: 14, width: "55%" }}></div>
      <div className="skl" style={{ height: 11, width: "100%" }}></div>
      <div className="skl" style={{ height: 11, width: "88%" }}></div>
      <div className="skl" style={{ height: 11, width: "40%", marginBottom: 0 }}></div>
    </div>
  );
}
