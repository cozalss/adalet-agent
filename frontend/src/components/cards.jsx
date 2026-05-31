/* ADALET /sor — cevap, reddetme, netleştirme, boş durum, kullanıcı balonu.
   Prototipten birebir; Icon/data ES import. */
import React, { useState, useEffect, useMemo } from "react";
import { Icon, DOMAINS, EXAMPLES } from "./icons.jsx";
import { RunText } from "./ui.jsx";

function toWordTokens(runs) {
  const toks = [];
  runs.forEach((r) => {
    if (r.cite != null) { toks.push({ cite: r.cite }); return; }
    const parts = r.t.split(/(\s+)/);
    parts.forEach((p) => { if (p !== "") toks.push({ w: p, sp: /^\s+$/.test(p) }); });
  });
  return toks;
}

export function TypingAnswer({ section, sources, speed }) {
  const tokens = useMemo(() => toWordTokens(section.runs), [section]);
  const [n, setN] = useState(0);
  const wordMs = Math.max(40, speed * 4.2);
  useEffect(() => {
    setN(0);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setN(tokens.length); return; }
    let i = 0;
    const id = setInterval(() => {
      i += 1; setN(i);
      if (i >= tokens.length) clearInterval(id);
    }, wordMs);
    return () => clearInterval(id);
  }, [tokens, wordMs]);

  const shown = tokens.slice(0, n);
  const done = n >= tokens.length;
  return (
    <div className="card answer">
      <div className="sec">
        <div className="sec-label">{section.label}</div>
        <p className="lead">
          {shown.map((t, i) =>
            t.cite != null
              ? <span className="cite" key={i} style={{ cursor: "default" }}>{t.cite}</span>
              : <span className={"tok" + (t.sp ? " sp" : "")} key={i}>{t.w}</span>
          )}
          {!done && <span className="type-caret"></span>}
        </p>
      </div>
    </div>
  );
}

export function AnswerCard({ answer, sources, onJump }) {
  return (
    <div className="card answer">
      {answer.sections.map((sec, i) => (
        <div className="sec" key={i}>
          <div className="sec-label">{sec.label}</div>
          {sec.steps ? (
            <ol className="steps">
              {sec.steps.map((st, j) => <li key={j}>{st}</li>)}
            </ol>
          ) : (
            <p className={sec.lead ? "lead" : ""}>
              <RunText runs={sec.runs} sources={sources} onJump={onJump} />
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

export function RejectCard({ data, onRetry }) {
  return (
    <div className="card reject">
      <div className="rj-head">
        <span className="rj-ic"><Icon.help /></span>
        <h4>{data.title}</h4>
      </div>
      <p>{data.body}</p>
      <div className="rj-actions">
        <button className="btn" onClick={onRetry}>Soruyu yeniden yaz</button>
        <a className="btn primary" href="https://barobirlik.org.tr" target="_blank" rel="noreferrer">
          Avukat bul <Icon.ext />
        </a>
      </div>
    </div>
  );
}

export function ClarifyCard({ data, onPick }) {
  return (
    <div className="card clarify">
      <p className="cl-q">{data.intro}</p>
      <div className="cl-opts">
        {data.options.map((o, i) => (
          <button className="cl-opt" key={i} onClick={() => onPick(o)}>
            <span className="num">{i + 1}</span>{o}
          </button>
        ))}
      </div>
    </div>
  );
}

export function UserBubble({ text }) {
  return <div className="msg user"><div className="bubble">{text}</div></div>;
}
