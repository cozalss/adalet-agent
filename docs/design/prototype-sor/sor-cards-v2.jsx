/* ============================================================
   ADALET /sor — answer, reject, clarify, empty-state, bubble
   ============================================================ */
const { useState: useStateC, useEffect: useEffectC, useRef: useRefC } = React;

/* flatten a section's runs into WORD tokens (words + citation objs) for blur-fade reveal */
function toWordTokens(runs) {
  const toks = [];
  runs.forEach((r) => {
    if (r.cite != null) { toks.push({ cite: r.cite }); return; }
    // split keeping the whitespace so spacing survives
    const parts = r.t.split(/(\s+)/);
    parts.forEach((p) => { if (p !== "") toks.push({ w: p, sp: /^\s+$/.test(p) }); });
  });
  return toks;
}

/* ---------- Typing lead (drafting phase) — word-by-word blur-fade ---------- */
function TypingAnswer({ section, sources, speed }) {
  const tokens = React.useMemo(() => toWordTokens(section.runs), [section]);
  const [n, setN] = useStateC(0);
  // approximate per-word cadence from the per-char speed so total timing matches the engine
  const wordMs = Math.max(40, speed * 4.2);
  useEffectC(() => {
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

/* ---------- Full answer card (final) ---------- */
function AnswerCard({ answer, sources, onJump }) {
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

/* ---------- Reject card ---------- */
function RejectCard({ data, onRetry }) {
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

/* ---------- Clarify card ---------- */
function ClarifyCard({ data, onPick }) {
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

/* ---------- User bubble ---------- */
function UserBubble({ text }) {
  return <div className="msg user"><div className="bubble">{text}</div></div>;
}

/* ---------- Empty state ---------- */
function EmptyState({ onAsk, onFill, InputSlot }) {
  return (
    <div className="empty">
      <h1 className="font-display">Merhaba, size nasıl<br />yardımcı olabilirim?</h1>
      <p className="sub">Hukuki sorunuzu gündelik dille yazın — kanun maddeleri ve mahkeme kararlarıyla yanıtlayayım.</p>

      <div className="big-input">{InputSlot}</div>

      <div className="quick-row">
        {DOMAINS.map((d) => {
          const I = Icon[d.icon];
          return (
            <button className="chip" key={d.id} onClick={() => onFill(d.label + " hukukuyla ilgili sorum: ")}>
              <I />{d.label}
            </button>
          );
        })}
      </div>

      <p className="block-label">Örnek sorular</p>
      <div className="examples">
        {EXAMPLES.map((e, i) => (
          <button className="example" key={i} onClick={() => onAsk(e.t)}>
            <span className="arr mono">›</span>{e.t}
          </button>
        ))}
      </div>

      <div className="recents">
        <p className="block-label">Son konuşmalar</p>
        {RECENTS.map((r, i) => (
          <button className="recent" key={i} onClick={() => onAsk(r.t)}>
            <span className="arr mono">›</span>{r.t}
            <span className="when">{r.when}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, {
  TypingAnswer, AnswerCard, RejectCard, ClarifyCard, UserBubble, EmptyState,
});
