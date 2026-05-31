/* ADALET /sor — cevap, reddetme, netleştirme, kullanıcı balonu.
   Prototipten birebir; Icon ES import. */
import React, { useState, useRef, useEffect } from "react";
import { Icon } from "./icons.jsx";
import { RunText } from "./ui.jsx";

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
              <RunText runs={sec.runs ?? []} sources={sources} onJump={onJump} />
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

export function UserBubble({ text, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(text);
  const ref = useRef(null);

  useEffect(() => {
    if (!editing || !ref.current) return;
    const el = ref.current;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [editing]);

  const save = () => {
    const t = val.trim();
    if (t && t !== text) onEdit?.(t);
    setEditing(false);
  };
  const cancel = () => { setVal(text); setEditing(false); };

  if (editing) {
    return (
      <div className="msg user editing">
        <div className="bubble edit">
          <textarea
            ref={ref} value={val} rows={1}
            onChange={(e) => { setVal(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px"; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(); }
              else if (e.key === "Escape") { e.preventDefault(); cancel(); }
            }}
            aria-label="Mesajı düzenle"
          />
          <div className="edit-actions">
            <button className="btn-sm" onClick={cancel}>Vazgeç</button>
            <button className="btn-sm primary" onClick={save}>Gönder</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="msg user">
      <div className="bubble">{text}</div>
      {onEdit && (
        <button className="bubble-edit" onClick={() => { setVal(text); setEditing(true); }} aria-label="Mesajı düzenle" title="Düzenle">
          <Icon.pencil />
        </button>
      )}
    </div>
  );
}
