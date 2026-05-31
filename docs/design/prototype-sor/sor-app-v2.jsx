/* ============================================================
   ADALET /sor — main app
   ============================================================ */
const { useState, useEffect, useRef, useCallback, useMemo } = React;

const ACCENTS = {
  Karamel: "#b0764a",
  Kiremit: "#a85c43",
  Zeytin: "#7d7a4e",
};

/* ---------- ChatGPT-style input pill ---------- */
function CGInput({ value, onChange, onSubmit, busy, autoFocus }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  }, [value]);
  useEffect(() => { if (autoFocus && ref.current) ref.current.focus(); }, [autoFocus]);
  const submit = () => { if (value.trim() && !busy) onSubmit(value.trim()); };
  const hasText = value.trim().length > 0;
  return (
    <div className="cg-shell">
      <button className="cg-round" aria-label="Ekle" tabIndex={-1}><Icon.plus /></button>
      <textarea
        ref={ref} rows={1} value={value}
        placeholder="Herhangi bir şey sor"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        disabled={busy}
      />
      <div className="cg-tools">
        <button className="cg-think" tabIndex={-1}><Icon.scale style={{ width: 14, height: 14 }} />Düşün<Icon.chevron /></button>
        <button className="cg-round" aria-label="Sesli" tabIndex={-1}><Icon.mic /></button>
        {hasText ? (
          <button className="cg-send go" onClick={submit} disabled={busy} aria-label="Gönder"><Icon.send /></button>
        ) : (
          <button className="cg-send voice" aria-label="Sesli mod" tabIndex={-1}><Icon.wave /></button>
        )}
      </div>
    </div>
  );
}

/* ---------- Sidebar ---------- */
function Sidebar({ collapsed, onToggle, onNew, started }) {
  return (
    <aside className={"sidebar" + (collapsed ? " collapsed" : "")}>
      <div className="sb-top">
        <div className="sb-brand"><span className="mark"><Icon.scale /></span>ADALET</div>
        <button className="icon-btn" onClick={onToggle} aria-label="Kenar çubuğunu gizle"><Icon.panel /></button>
      </div>

      <nav className="sb-nav">
        {SB_NAV.map((n) => {
          const I = Icon[n.icon];
          return (
            <button className={"sb-item" + (n.id === "new" ? " primary" : "")} key={n.id} onClick={n.id === "new" ? onNew : undefined}>
              <I />{n.label}
            </button>
          );
        })}
      </nav>

      <div className="sb-section-label">Yakın zamandakiler</div>
      <div className="sb-list">
        {SB_CHATS.map((c, i) => (
          <button className={"sb-chat" + (started && i === 0 ? " active" : "")} key={i}>
            <span className="label">{c.t}</span>
            {c.pin && <span className="pin"><Icon.pin /></span>}
          </button>
        ))}
      </div>

      <div className="sb-user">
        <span className="avatar">C</span>
        <span className="who"><b>Cem Özal</b><span>Plus</span></span>
        <span className="grid-ic"><Icon.grid /></span>
      </div>
    </aside>
  );
}

/* ---------- build per-turn data from a scenario ---------- */
function buildData(scn) {
  if (scn.kind === "answer")
    return { kind: "answer", sources: scn.sources, answer: scn.answer, risk: scn.risk, domain: scn.domain };
  if (scn.kind === "reject")
    return { kind: "reject", reject: scn.reject, lookedAt: scn.lookedAt, domain: scn.domain };
  return { kind: "clarify", clarify: scn.clarify, resolved: scn.resolved, domain: scn.domain };
}

const TERMINAL = ["final", "reject"];

function App() {
  const [t, setTweak] = useTweaks({
    theme: "warm",
    accent: "#b0764a",
    typeSpeed: 18,
    scenario: "auto",
  });
  const [turns, setTurns] = useState([]);
  const [input, setInput] = useState("");
  const [flash, setFlash] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 760);
  const [srcW, setSrcW] = useState(() => {
    const v = localStorage.getItem("sor-srcw"); return v ? +v : null;
  });

  const scrollRef = useRef(null);
  const panelRef = useRef(null);
  const srcRefs = useRef({});

  /* apply theme + accent to <html> */
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", t.theme);
    document.documentElement.style.setProperty("--accent", t.accent);
    // derive soft + text variants
    document.documentElement.style.setProperty("--accent-soft", hexA(t.accent, t.theme === "navy" ? 0.16 : 0.13));
    document.documentElement.style.setProperty("--accent-text", t.theme === "navy" ? lighten(t.accent, 18) : darken(t.accent, 12));
  }, [t.theme, t.accent]);

  const last = turns[turns.length - 1];
  const busy = last && !TERMINAL.includes(last.phase) && last.phase !== "clarify";
  const started = turns.length > 0;

  /* keep scrolled to bottom while streaming */
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns, last && last.phase]);

  /* ---------- streaming engine ---------- */
  useEffect(() => {
    const i = turns.length - 1; if (i < 0) return;
    const turn = turns[i];
    const set = (phase, extra) => setTurns((ts) => ts.map((x, k) => (k === i ? { ...x, phase, ...extra } : x)));
    const d = turn.data;
    let id;
    if (turn.phase === "triage") {
      id = setTimeout(() => {
        if (d.kind === "clarify") set("clarify");
        else if (d.kind === "reject") set("searching");
        else set("sources");
      }, 950);
    } else if (turn.phase === "searching") {
      id = setTimeout(() => set("reject"), 1500);
    } else if (turn.phase === "sources") {
      id = setTimeout(() => set("drafting"), 1500);
    } else if (turn.phase === "drafting") {
      const toks = d.answer.sections[0].runs.reduce((a, r) => a + (r.cite != null ? 1 : r.t.length), 0);
      id = setTimeout(() => set("final"), toks * t.typeSpeed + 800);
    }
    return () => clearTimeout(id);
  }, [turns, t.typeSpeed]);

  /* ---------- actions ---------- */
  const ask = useCallback((text) => {
    const scn = SCENARIOS[pickScenario(text, t.scenario)];
    setTurns((ts) => [...ts, { key: Date.now(), question: text, phase: "triage", data: buildData(scn) }]);
    setInput("");
    setSheetOpen(false);
  }, [t.scenario]);

  const onClarifyPick = useCallback((opt) => {
    setTurns((ts) => ts.map((x, k) => {
      if (k !== ts.length - 1) return x;
      const r = x.data.resolved;
      return {
        ...x, phase: "sources", clarifyPicked: opt,
        data: { ...x.data, kind: "answer", sources: r.sources, answer: r.answer, risk: r.risk },
      };
    }));
  }, []);

  const [beam, setBeam] = useState(null);

  const jumpToSource = useCallback((n, citeEl) => {
    const startRect = citeEl ? citeEl.getBoundingClientRect() : null;
    setSheetOpen(true);
    setFlash(n);
    // wait for the drawer to slide in, then scroll the card into view
    setTimeout(() => {
      const el = srcRefs.current[n];
      const sc = panelRef.current;
      if (el && sc) sc.scrollTo({ top: el.offsetTop - 16, behavior: "smooth" });
      // draw the beam once the card has settled
      setTimeout(() => {
        const card = document.querySelector('[data-src-id="' + n + '"]');
        if (startRect && card) {
          const er = card.getBoundingClientRect();
          setBeam({
            x1: startRect.right, y1: startRect.top + startRect.height / 2,
            x2: er.left + 10, y2: er.top + 24, key: Date.now(),
          });
        }
      }, 240);
    }, 340);
    setTimeout(() => setFlash(null), 1900);
    setTimeout(() => setBeam(null), 1700);
  }, []);

  /* ---------- resize handle ---------- */
  const startResize = (e) => {
    e.preventDefault();
    const move = (ev) => {
      const total = document.querySelector(".panels").getBoundingClientRect();
      let w = total.right - ev.clientX;
      w = Math.max(320, Math.min(560, w));
      setSrcW(w);
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      document.body.style.userSelect = "";
    };
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  useEffect(() => { if (srcW != null) localStorage.setItem("sor-srcw", srcW); }, [srcW]);

  /* ---------- source panel content (from last answer/reject turn) ---------- */
  const srcTurn = useMemo(() => {
    for (let k = turns.length - 1; k >= 0; k--) {
      const d = turns[k].data;
      if ((d.kind === "answer" && (turns[k].phase !== "triage")) || d.kind === "reject") return turns[k];
    }
    return null;
  }, [turns]);

  const domain = last ? last.data.domain : null;
  const sourceCount = srcTurn && srcTurn.data.sources ? srcTurn.data.sources.length : 0;
  const showSourcesReady = srcTurn && ["drafting", "final"].includes(srcTurn.phase);

  return (
    <div className="sor-app">
      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
        onNew={() => { setTurns([]); setInput(""); setSheetOpen(false); }}
        started={started}
      />

      {/* Main column */}
      <div className="main-col">
        {sidebarCollapsed && (
          <button className="float-toggle" onClick={() => setSidebarCollapsed(false)} aria-label="Kenar çubuğunu aç"><Icon.panel /></button>
        )}

        <header className="main-head">
          <button className="model" style={sidebarCollapsed ? { marginLeft: 40 } : undefined}>
            ADALET <span className="sub">5.0</span> <Icon.chevron />
          </button>
          {domain && <span className="domain-chip"><span className="dot"></span>{domain}</span>}
          <div className="spacer"></div>
          {sourceCount > 0 && showSourcesReady && (
            <button className="src-pill" onClick={() => setSheetOpen(true)}>
              <Icon.book />Kaynaklar <span className="badge kanun">{sourceCount}</span>
            </button>
          )}
        </header>

        <div className="panels">
          <section className="chat-panel">
            {!started ? (
              <div className="cg-hero">
                <h1 className="cg-greet">Nasıl yardımcı olabilirim, <span className="accent">Cem</span>?</h1>
                <div className="cg-input-wrap">
                  <CGInput value={input} onChange={setInput} onSubmit={ask} busy={false} autoFocus />
                  <div className="cg-suggest">
                    {CG_SUGGEST.map((s) => {
                      const I = Icon[s.icon];
                      return (
                        <button className="cg-chip" key={s.label} onClick={() => setInput(s.label + ": ")}>
                          <I />{s.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <React.Fragment>
                <div className="chat-scroll" ref={scrollRef}>
                  <div className="chat-inner">
                    {turns.map((turn) => (
                      <TurnView
                        key={turn.key} turn={turn} typeSpeed={t.typeSpeed}
                        onJump={jumpToSource}
                        onRetry={() => { setTurns((ts) => ts.slice(0, -1)); setInput(turn.question); }}
                        onClarifyPick={onClarifyPick}
                      />
                    ))}
                  </div>
                </div>
                <div className="cg-dock">
                  <div className="wrap">
                    <CGInput value={input} onChange={setInput} onSubmit={ask} busy={busy} />
                    <p className="hint">ADALET yanıtları kaynaklıdır ancak hata yapabilir · hukuki danışmanlık değildir.</p>
                  </div>
                </div>
              </React.Fragment>
            )}
          </section>
        </div>
      </div>

      {/* Source drawer + backdrop */}
      <div className={"sheet-backdrop" + (sheetOpen ? " open" : "")} onClick={() => setSheetOpen(false)}></div>
      <aside className={"source-panel drawer " + (sheetOpen ? "open" : "closed")} ref={panelRef}>
        <div className="drawer-head">
          <h3>Kaynaklar</h3>
          <button className="icon-btn" onClick={() => setSheetOpen(false)} aria-label="Kapat"><Icon.plus style={{ transform: "rotate(45deg)" }} /></button>
        </div>
        <div className="source-inner" style={{ paddingTop: 6 }}>
          <SourcePanelBody
            turn={srcTurn} flash={flash} hideHead
            registerRef={(n, el) => { srcRefs.current[n] = el; }}
          />
        </div>
      </aside>

      {/* Animated beam overlay */}
      {beam && <BeamLayer beam={beam} />}

      {/* Tweaks */}
      <TweaksPanel>
        <TweakSection label="Tema" />
        <TweakRadio
          label="Renk teması"
          value={t.theme}
          options={[{ label: "Sıcak (landing)", value: "warm" }, { label: "Lacivert (spec)", value: "navy" }]}
          onChange={(v) => setTweak("theme", v)}
        />
        <TweakColor
          label="Vurgu rengi"
          value={t.accent}
          options={Object.values(ACCENTS)}
          onChange={(v) => setTweak("accent", v)}
        />
        <TweakSection label="Akış" />
        <TweakSlider
          label="Yazım hızı" value={t.typeSpeed} min={4} max={45} step={1} unit="ms/krk"
          onChange={(v) => setTweak("typeSpeed", v)}
        />
        <TweakSelect
          label="Demo senaryosu"
          value={t.scenario}
          options={[
            { label: "Otomatik (soruya göre)", value: "auto" },
            { label: "Cevap + kaynaklar", value: "ayipli" },
            { label: "Netleştirme sorusu", value: "tahliye" },
            { label: "Nazik reddetme", value: "reject" },
          ]}
          onChange={(v) => setTweak("scenario", v)}
        />
      </TweaksPanel>
    </div>
  );
}

/* ---------- one conversation turn ---------- */
function TurnView({ turn, typeSpeed, onJump, onRetry, onClarifyPick }) {
  const d = turn.data;
  const p = turn.phase;
  const streaming = ["triage", "searching", "sources", "drafting"].includes(p);
  const stepperPhase = p === "searching" ? "sources" : p;
  return (
    <React.Fragment>
      <UserBubble text={turn.question} />
      <div className="assistant-row">
        <span className="ava"><Icon.scale /></span>
        <div className="assistant-body">
          {streaming && p !== "clarify" && (
            <StreamStepper phase={stepperPhase} customLabel={SCENARIOS_label(turn)} />
          )}

          {d.kind === "clarify" && p === "clarify" && (
            <ClarifyCard data={d.clarify} onPick={onClarifyPick} />
          )}

          {d.risk && ["drafting", "final"].includes(p) && <RiskWarning html={d.risk.text} />}

          {p === "drafting" && d.answer && (
            <TypingAnswer section={d.answer.sections[0]} sources={d.sources} speed={typeSpeed} />
          )}

          {p === "final" && d.answer && (
            <React.Fragment>
              <AnswerCard answer={d.answer} sources={d.sources} onJump={onJump} />
              <ConfidenceBar value={d.answer.confidence} count={d.sources.length} />
              <DisclaimerBar />
            </React.Fragment>
          )}

          {p === "reject" && <RejectCard data={d.reject} onRetry={onRetry} />}
        </div>
      </div>
    </React.Fragment>
  );
}

function SCENARIOS_label(turn) {
  // triage custom label from scenario
  const found = Object.values(SCENARIOS).find((s) => s.question === turn.question);
  return found ? found.triageLabel : null;
}

/* ---------- source panel body ---------- */
function SourcePanelBody({ turn, flash, registerRef, hideHead }) {
  if (!turn) {
    return (
      <div className="source-empty">
        <Icon.book />
        <div>Yanıtların dayandığı kanun maddeleri ve mahkeme kararları burada görünür.</div>
      </div>
    );
  }
  const d = turn.data;
  const p = turn.phase;

  if (d.kind === "reject") {
    return (
      <React.Fragment>
        {!hideHead && <div className="source-head"><h3>Kaynaklar</h3></div>}
        <div className="source-empty" style={{ padding: "30px 6px", maxWidth: "none" }}>
          <Icon.search />
          <div style={{ marginBottom: 14 }}>Bakılan ama soruyla güvenle eşleşmeyen kaynaklar:</div>
          {d.lookedAt.map((x, i) => (
            <div key={i} className="mono" style={{ fontSize: 12, color: "var(--text-3)", padding: "6px 0", borderTop: "1px solid var(--border)" }}>{x}</div>
          ))}
        </div>
      </React.Fragment>
    );
  }

  const ready = ["drafting", "final"].includes(p);
  const loading = p === "sources";
  return (
    <React.Fragment>
      {!hideHead && (
        <div className="source-head">
          <h3>Kaynaklar</h3>
          {ready && <span className="count mono">{d.sources.length} kaynak</span>}
        </div>
      )}
      {hideHead && ready && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
          <span className="count mono">{d.sources.length} kaynak</span>
        </div>
      )}
      {loading && [0, 1, 2].map((i) => <SourceSkeleton key={i} />)}
      {ready && d.sources.map((s) => (
        <SourceCard key={s.id} s={s} flash={flash === s.id} onRef={(el) => registerRef(s.id, el)} />
      ))}
    </React.Fragment>
  );
}

/* ---------- Animated beam: citation → source card (Magic UI signature) ---------- */
function BeamLayer({ beam }) {
  const { x1, y1, x2, y2 } = beam;
  // horizontal-biased cubic so the beam arcs gracefully into the drawer
  const dx = Math.max(80, (x2 - x1) * 0.5);
  const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  return (
    <svg className="beam-layer" key={beam.key}>
      <defs>
        <linearGradient id="beamGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0" />
          <stop offset="35%" stopColor="var(--accent)" stopOpacity="0.9" />
          <stop offset="100%" stopColor="var(--accent)" />
        </linearGradient>
      </defs>
      <path id={"beamP" + beam.key} className="beam-path" d={d} style={{ opacity: 0.45 }} />
      <path className="beam-dash" d={d} />
      <circle className="beam-spark" r="3.5">
        <animateMotion dur="1.1s" repeatCount="indefinite">
          <mpath href={"#beamP" + beam.key} />
        </animateMotion>
      </circle>
    </svg>
  );
}

/* ---------- color helpers ---------- */
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
function lighten(hex, amt) { return shift(hex, amt); }
function darken(hex, amt) { return shift(hex, -amt); }
function shift(hex, amt) {
  let r = (parseInt(hex.slice(1, 3), 16) + amt);
  let g = (parseInt(hex.slice(3, 5), 16) + amt);
  let b = (parseInt(hex.slice(5, 7), 16) + amt);
  const c = (x) => Math.max(0, Math.min(255, x)).toString(16).padStart(2, "0");
  return "#" + c(r) + c(g) + c(b);
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
