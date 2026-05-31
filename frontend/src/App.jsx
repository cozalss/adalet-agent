/* ADALET /sor — ana uygulama (gerçek backend'e bağlı).
   Prototip tasarımı korunur; mock motor yerine useChat (SSE). */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Icon, SB_NAV, CG_SUGGEST, DOMAINS, EXAMPLES } from "./components/icons.jsx";
import {
  StreamStepper, ConfidenceBar, RiskWarning, DisclaimerBar, SourceCard, SourceSkeleton,
} from "./components/ui.jsx";
import {
  TypingAnswer, AnswerCard, RejectCard, ClarifyCard, UserBubble,
} from "./components/cards.jsx";
import { useChat } from "./hooks/useChat.js";
import { ocrUpload, downloadDilekce } from "./lib/api.js";
import "./styles/sor.css";
import "./styles/sor-pro.css";
import "./styles/app-extra.css";

const SB_CHATS = [
  { t: "Ayıplı telefon iadesi", pin: true },
  { t: "Kira artış oranı itirazı", pin: true },
  { t: "Kıdem tazminatı hesabı" },
  { t: "Tüketici hakem heyeti başvurusu" },
];

/* ---------- ChatGPT-style input pill ---------- */
function CGInput({ value, onChange, onSubmit, busy, autoFocus, onAttach, attachCount, wantDilekce, onToggleDilekce, onStop }) {
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
      <button className="cg-round" aria-label="Belge ekle (OCR)" onClick={onAttach} title="Belge ekle">
        <Icon.plus />
        {attachCount > 0 && <span className="attach-badge">{attachCount}</span>}
      </button>
      <textarea
        ref={ref} rows={1} value={value}
        placeholder={attachCount > 0 ? "Belgeyle ilgili sorunuzu yazın…" : "Herhangi bir şey sor"}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        disabled={busy}
      />
      <div className="cg-tools">
        <button
          className={"cg-think" + (wantDilekce ? " on" : "")}
          onClick={onToggleDilekce}
          title="Cevapla birlikte dilekçe taslağı da hazırla"
        >
          <Icon.pencil style={{ width: 14, height: 14 }} />Dilekçe<Icon.chevron />
        </button>
        {busy ? (
          <button className="cg-send stop" onClick={onStop} aria-label="Yanıtı durdur" title="Yanıtı durdur"><Icon.stop /></button>
        ) : hasText ? (
          <button className="cg-send go" onClick={submit} aria-label="Gönder"><Icon.send /></button>
        ) : (
          <button className="cg-send voice" aria-label="Sesli mod (yakında)" title="Sesli mod — yakında" disabled><Icon.wave /></button>
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

export default function App() {
  const { turns, ask, stop, pickClarify, retryLast, reset, busy, conversationId } = useChat();
  const [input, setInput] = useState("");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 760);
  const [flash, setFlash] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [wantDilekce, setWantDilekce] = useState(false);
  const [toast, setToast] = useState(null);

  const scrollRef = useRef(null);
  const panelRef = useRef(null);
  const srcRefs = useRef({});
  const fileRef = useRef(null);

  const last = turns[turns.length - 1];
  const started = turns.length > 0;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns, last && last.phase]);

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3200); };

  const doAsk = useCallback((text) => {
    const opts = { wantDilekce, attachments: attachments.length ? attachments : undefined };
    ask(text, opts);
    setInput("");
    setAttachments([]);
    setSheetOpen(false);
  }, [ask, wantDilekce, attachments]);

  /* ---------- OCR upload ---------- */
  const onAttach = () => fileRef.current?.click();
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    showToast("Belge okunuyor (OCR)…");
    try {
      const res = await ocrUpload(file);
      if (!res.text || res.text.length < 5) { showToast("Belgeden metin çıkarılamadı."); return; }
      setAttachments((a) => [...a, {
        filename: file.name, ocr_engine: res.engine || "tesseract",
        text: res.text.slice(0, 10000), n_chars: res.n_chars || res.text.length,
      }]);
      showToast(`Belge eklendi: ${file.name} (${res.n_chars || res.text.length} karakter)`);
    } catch (err) {
      showToast("OCR başarısız — backend çalışıyor mu?");
    }
  };

  /* ---------- dilekçe download ---------- */
  const onDownloadDilekce = async (fmt) => {
    if (!conversationId) return;
    try { await downloadDilekce(conversationId, fmt); }
    catch { showToast("Dilekçe bulunamadı. Soruyu 'Dilekçe' açıkken sorun."); }
  };

  /* ---------- citation → source beam ---------- */
  const [beam, setBeam] = useState(null);
  const jumpToSource = useCallback((n, citeEl) => {
    const startRect = citeEl ? citeEl.getBoundingClientRect() : null;
    setSheetOpen(true);
    setFlash(n);
    setTimeout(() => {
      const el = srcRefs.current[n];
      const sc = panelRef.current;
      if (el && sc) sc.scrollTo({ top: el.offsetTop - 16, behavior: "smooth" });
      setTimeout(() => {
        const card = document.querySelector('[data-src-id="' + n + '"]');
        if (startRect && card) {
          const er = card.getBoundingClientRect();
          setBeam({ x1: startRect.right, y1: startRect.top + startRect.height / 2,
            x2: er.left + 10, y2: er.top + 24, key: Date.now() });
        }
      }, 240);
    }, 340);
    setTimeout(() => setFlash(null), 1900);
    setTimeout(() => setBeam(null), 1700);
  }, []);

  /* ---------- source panel content ---------- */
  const srcTurn = useMemo(() => {
    for (let k = turns.length - 1; k >= 0; k--) {
      const d = turns[k].data;
      if ((d.kind === "answer" && turns[k].phase !== "triage") || d.kind === "reject") return turns[k];
    }
    return null;
  }, [turns]);

  const domain = last ? last.data.domain : null;
  const domainConf = last ? last.data.domainConfidence : null;
  const domainLow = domainConf != null && domainConf < 0.5;
  const srcCount = srcTurn ? (srcTurn.data.sources?.length || srcTurn.data.sourceCount || 0) : 0;
  const showSrcPill = srcTurn && ["sources", "drafting", "final"].includes(srcTurn.phase) && srcCount > 0;

  return (
    <div className="sor-app">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
        onNew={reset}
        started={started}
      />
      <input ref={fileRef} type="file" accept="image/*,application/pdf" hidden onChange={onFile} />

      <div className="main-col">
        {sidebarCollapsed && (
          <button className="float-toggle" onClick={() => setSidebarCollapsed(false)} aria-label="Kenar çubuğunu aç"><Icon.panel /></button>
        )}

        <header className="main-head">
          <button className="model" style={sidebarCollapsed ? { marginLeft: 40 } : undefined}>
            ADALET <span className="sub">5.0</span> <Icon.chevron />
          </button>
          {domain && (
            <span
              className={"domain-chip" + (domainLow ? " low" : "")}
              title={domainConf != null ? `Alan güveni %${Math.round(domainConf * 100)}` : undefined}
            >
              <span className="dot"></span>{domain}{domainLow ? " · belirsiz" : ""}
            </span>
          )}
          <div className="spacer"></div>
          {showSrcPill && (
            <button className="src-pill" onClick={() => setSheetOpen(true)}>
              <Icon.book />Kaynaklar <span className="badge kanun">{srcCount}</span>
            </button>
          )}
        </header>

        <div className="panels">
          <section className="chat-panel">
            {!started ? (
              <div className="cg-hero">
                <h1 className="cg-greet">Nasıl yardımcı olabilirim, <span className="accent">Cem</span>?</h1>
                <div className="cg-input-wrap">
                  <CGInput
                    value={input} onChange={setInput} onSubmit={doAsk} busy={false} autoFocus
                    onAttach={onAttach} attachCount={attachments.length}
                    wantDilekce={wantDilekce} onToggleDilekce={() => setWantDilekce((v) => !v)}
                    onStop={stop}
                  />
                  {attachments.length > 0 && <AttachRow attachments={attachments} onClear={() => setAttachments([])} />}
                  <div className="cg-suggest">
                    {CG_SUGGEST.map((s) => {
                      const I = Icon[s.icon];
                      return (
                        <button className="cg-chip" key={s.label} onClick={() => {
                          if (s.label === "Dilekçe taslağı") setWantDilekce(true);
                          setInput(s.label + ": ");
                        }}>
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
                        key={turn.key} turn={turn}
                        onJump={jumpToSource}
                        onRetry={() => setInput(retryLast())}
                        onReask={ask}
                        onClarifyPick={pickClarify}
                        onToast={showToast}
                        onDownloadDilekce={onDownloadDilekce}
                      />
                    ))}
                  </div>
                </div>
                <div className="cg-dock">
                  <div className="wrap">
                    {attachments.length > 0 && <AttachRow attachments={attachments} onClear={() => setAttachments([])} />}
                    <CGInput
                      value={input} onChange={setInput} onSubmit={doAsk} busy={busy}
                      onAttach={onAttach} attachCount={attachments.length}
                      wantDilekce={wantDilekce} onToggleDilekce={() => setWantDilekce((v) => !v)}
                      onStop={stop}
                    />
                    <p className="hint">ADALET yanıtları kaynaklıdır ancak hata yapabilir · hukuki danışmanlık değildir.</p>
                  </div>
                </div>
              </React.Fragment>
            )}
          </section>
        </div>
      </div>

      <div className={"sheet-backdrop" + (sheetOpen ? " open" : "")} onClick={() => setSheetOpen(false)}></div>
      <aside className={"source-panel drawer " + (sheetOpen ? "open" : "closed")} ref={panelRef}>
        <div className="drawer-head">
          <h3>Kaynaklar</h3>
          <button className="icon-btn" onClick={() => setSheetOpen(false)} aria-label="Kapat"><Icon.plus style={{ transform: "rotate(45deg)" }} /></button>
        </div>
        <div className="source-inner" style={{ paddingTop: 6 }}>
          <SourcePanelBody turn={srcTurn} flash={flash} registerRef={(n, el) => { srcRefs.current[n] = el; }} />
        </div>
      </aside>

      {beam && <BeamLayer beam={beam} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

/* ---------- attachment chips ---------- */
function AttachRow({ attachments, onClear }) {
  return (
    <div className="attach-row">
      {attachments.map((a, i) => (
        <span className="attach-chip" key={i}><Icon.image style={{ width: 13, height: 13 }} />{a.filename}</span>
      ))}
      <button className="attach-clear" onClick={onClear}>temizle</button>
    </div>
  );
}

/* ---------- one conversation turn ---------- */
function TurnView({ turn, onJump, onRetry, onReask, onClarifyPick, onToast, onDownloadDilekce }) {
  const d = turn.data;
  const p = turn.phase;
  const streaming = ["triage", "sources", "drafting"].includes(p);
  return (
    <React.Fragment>
      <UserBubble text={turn.question} />
      <div className="assistant-row">
        <span className="ava"><Icon.scale /></span>
        <div className="assistant-body">
          {streaming && <StreamStepper phase={p} customLabel={d.domain ? `Soru sınıflandırıldı — ${d.domain}` : null} />}

          {d.kind === "clarify" && p === "clarify" && (
            <ClarifyCard data={d.clarify} onPick={onClarifyPick} />
          )}

          {d.risk && p === "final" && <RiskWarning html={d.risk.text} />}

          {p === "final" && d.answer && (
            <React.Fragment>
              <AnswerCard answer={d.answer} sources={d.sources} onJump={onJump} />
              <ConfidenceBar value={d.answer.confidence} count={d.sources.length} />
              {d.hasDilekce && (
                <div className="dilekce-bar">
                  <button className="btn ghost" onClick={() => onDownloadDilekce("pdf")}><Icon.download /> Dilekçe (PDF)</button>
                  <button className="btn ghost" onClick={() => onDownloadDilekce("docx")}><Icon.download /> Dilekçe (Word)</button>
                </div>
              )}
              <MsgActions
                text={d.answer.text}
                onReask={() => onReask(turn.question)}
                onToast={onToast}
              />
              <DisclaimerBar items={d.disclaimers} />
            </React.Fragment>
          )}

          {p === "reject" && <RejectCard data={d.reject} onRetry={onRetry} />}
        </div>
      </div>
    </React.Fragment>
  );
}

/* ---------- mesaj eylem çubuğu (hover'da belirir): kopyala / yeniden sor / geri bildirim ---------- */
function MsgActions({ text, onReask, onToast }) {
  const [copied, setCopied] = useState(false);
  const [vote, setVote] = useState(null); // "up" | "down" | null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      onToast?.("Kopyalanamadı — tarayıcı izni gerekebilir.");
    }
  };
  // KVKK: geri bildirim ANONİM — kişisel veri yok. Şimdilik yerel sinyal +
  // teşekkür toast'u; eval döngüsüne (Langfuse) bağlama sonraki iterasyonda.
  const sendVote = (v) => {
    setVote(v);
    onToast?.(v === "up" ? "Teşekkürler — geri bildiriminiz alındı." : "Teşekkürler — bunu iyileştireceğiz.");
  };

  return (
    <div className="msg-actions" role="group" aria-label="Yanıt eylemleri">
      <button className="msg-action" onClick={copy} title="Yanıtı kopyala" aria-label="Yanıtı kopyala">
        {copied ? <Icon.check /> : <Icon.copy />}<span>{copied ? "Kopyalandı" : "Kopyala"}</span>
      </button>
      <button className="msg-action" onClick={onReask} title="Aynı soruyu yeniden sor" aria-label="Yeniden sor">
        <Icon.refresh /><span>Yeniden sor</span>
      </button>
      <span className="msg-sep" aria-hidden="true"></span>
      <button
        className={"msg-action icon" + (vote === "up" ? " on" : "")}
        onClick={() => sendVote("up")} title="Faydalı" aria-label="Faydalı" aria-pressed={vote === "up"}
      ><Icon.like /></button>
      <button
        className={"msg-action icon" + (vote === "down" ? " on" : "")}
        onClick={() => sendVote("down")} title="Faydalı değil" aria-label="Faydalı değil" aria-pressed={vote === "down"}
      ><Icon.dislike /></button>
    </div>
  );
}

/* ---------- source panel body ---------- */
function SourcePanelBody({ turn, flash, registerRef }) {
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
      <div className="source-empty" style={{ padding: "30px 6px", maxWidth: "none" }}>
        <Icon.search />
        <div style={{ marginBottom: 14 }}>Bakılan ama soruyla güvenle eşleşmeyen kaynaklar:</div>
        {(d.lookedAt || []).map((x, i) => (
          <div key={i} className="mono" style={{ fontSize: 12, color: "var(--text-3)", padding: "6px 0", borderTop: "1px solid var(--border)" }}>{x}</div>
        ))}
      </div>
    );
  }

  const ready = p === "final" && (d.sources || []).length > 0;
  const loading = ["sources", "drafting"].includes(p);
  const skelCount = Math.max(1, Math.min(d.sourceCount || 3, 5));
  return (
    <React.Fragment>
      {ready && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
          <span className="count mono">{d.sources.length} kaynak</span>
        </div>
      )}
      {loading && Array.from({ length: skelCount }).map((_, i) => <SourceSkeleton key={i} />)}
      {ready && d.sources.map((s) => (
        <SourceCard key={s.id} s={s} flash={flash === s.id} onRef={(el) => registerRef(s.id, el)} />
      ))}
    </React.Fragment>
  );
}

/* ---------- animated beam: citation → source card ---------- */
function BeamLayer({ beam }) {
  const { x1, y1, x2, y2 } = beam;
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
        <animateMotion dur="1.1s" repeatCount="indefinite"><mpath href={"#beamP" + beam.key} /></animateMotion>
      </circle>
    </svg>
  );
}
