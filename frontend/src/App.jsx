/* ADALET /sor — ana uygulama (gerçek backend'e bağlı).
   Prototip tasarımı korunur; mock motor yerine useChat (SSE). */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Icon, SB_NAV, DOMAIN_CARDS } from "./components/icons.jsx";
import {
  StreamStepper, RiskWarning, DisclaimerBar, SourceCard, SourceSkeleton,
} from "./components/ui.jsx";
import { AnswerCard, RejectCard, ClarifyCard, UserBubble } from "./components/cards.jsx";
import { AgentTrace, PredictionCard, ThinkingSkeleton, EvidenceStats } from "./components/panels.jsx";
import { useChat } from "./hooks/useChat.js";
import { DEMO_TURN } from "./lib/demoTurn.js";

// Önizleme modu: ?preview=1 → backend olmadan tam cevap UI'ı (tasarım QA + demo).
const PREVIEW = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("preview");

// OCR belge metni üst sınırı — backend api/schemas._MAX_ATTACHMENT_TEXT ile
// EŞLEŞMELİ (aşılırsa backend 422 döner). Değiştirirsen ikisini birlikte güncelle.
const MAX_OCR_CHARS = 10000;

// OCR PII şeffaflığı (KVKK): backend pii_counts anahtarları → Türkçe etiket.
const PII_LABELS = { tckn: "TC Kimlik No", phone: "telefon", email: "e-posta", iban: "IBAN", plate: "plaka" };
function formatPii(counts) {
  return Object.entries(counts || {})
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} ${PII_LABELS[k] || k}`)
    .join(", ");
}
import { ocrUpload, downloadDilekce } from "./lib/api.js";
import "./styles/sor.css";
import "./styles/sor-pro.css";
import "./styles/app-extra.css";

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
function Sidebar({ collapsed, onToggle, onNew, currentTitle }) {
  return (
    <aside className={"sidebar" + (collapsed ? " collapsed" : "")}>
      <div className="sb-top">
        <div className="sb-brand"><span className="mark"><Icon.scale /></span>ADALET</div>
        <button className="icon-btn" onClick={onToggle} aria-label="Kenar çubuğunu gizle"><Icon.panel /></button>
      </div>
      <nav className="sb-nav">
        {SB_NAV.map((n) => {
          const I = Icon[n.icon];
          const placeholder = n.id !== "new"; // ara/kaynaklar/dosyalar henüz yok
          return (
            <button
              className={"sb-item" + (n.id === "new" ? " primary" : "")}
              key={n.id}
              onClick={n.id === "new" ? onNew : undefined}
              disabled={placeholder}
              title={placeholder ? "Yakında" : undefined}
            >
              <I />{n.label}{placeholder && <span className="soon">yakında</span>}
            </button>
          );
        })}
      </nav>
      <div className="sb-section-label">Bu oturum</div>
      <div className="sb-list">
        {currentTitle ? (
          <button className="sb-chat active" title={currentTitle}>
            <span className="label">{currentTitle}</span>
          </button>
        ) : (
          <p className="sb-empty-note">
            <Icon.info style={{ width: 13, height: 13 }} />
            Gizliliğiniz için sohbet geçmişi saklanmaz — “Yeni sohbet” her şeyi siler, sıfırdan başlar.
          </p>
        )}
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
  const { turns: chatTurns, ask, stop, pickClarify, retryLast, editFrom, reset, undoReset, busy, conversationId } = useChat();
  const turns = PREVIEW ? [DEMO_TURN] : chatTurns;
  const [input, setInput] = useState("");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 760);
  const [flash, setFlash] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [wantDilekce, setWantDilekce] = useState(false);
  const [toast, setToast] = useState(null);
  const [atBottom, setAtBottom] = useState(true);

  const scrollRef = useRef(null);
  const panelRef = useRef(null);
  const srcRefs = useRef({});
  const fileRef = useRef(null);

  const last = turns[turns.length - 1];
  const started = turns.length > 0;

  // stick-to-bottom (vercel deseni, kütüphanesiz): yalnız kullanıcı en alttaysa
  // otomatik kaydır — yukarı çıkıp eski cevap okurken stream zıplatmasın.
  const onChatScroll = useCallback(() => {
    const el = scrollRef.current; if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  }, []);
  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current; if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);
  useEffect(() => {
    if (atBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [turns, last?.phase, atBottom]);

  // Drawer erişilebilirliği (Üye-2 "Erişilebilir Hukuk"): aç→ilk öğeye focus,
  // Esc→kapat, Tab→tuzak (odak drawer'da kalır), kapat→açan öğeye focus geri.
  const drawerReturnRef = useRef(null);
  useEffect(() => {
    if (!sheetOpen) return;
    drawerReturnRef.current = document.activeElement;
    const el = panelRef.current; if (!el) return;
    const SEL = 'button, [href], input, textarea, [tabindex]:not([tabindex="-1"])';
    const focusables = () =>
      Array.from(el.querySelectorAll(SEL)).filter((n) => !n.disabled && n.offsetParent !== null);
    focusables()[0]?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); setSheetOpen(false); return; }
      if (e.key !== "Tab") return;
      const f = focusables(); if (!f.length) return;
      const first = f[0], lastEl = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      drawerReturnRef.current?.focus?.();
    };
  }, [sheetOpen]);

  // toast: { msg, action? } — action = { label, onClick } (Vuetify snackbar-with-action).
  const toastTimer = useRef(null);
  const showToast = useCallback((msg, action = null) => {
    clearTimeout(toastTimer.current);
    setToast({ msg, action });
    toastTimer.current = setTimeout(() => setToast(null), action ? 6000 : 3200);
  }, []);
  const dismissToast = useCallback(() => { clearTimeout(toastTimer.current); setToast(null); }, []);

  // "Yeni sohbet": sil + geri-al snackbar'ı göster (silme 6sn geciktirilir).
  const onNewChat = useCallback(() => {
    if (reset()) {
      showToast("Sohbet temizlendi", { label: "Geri al", onClick: undoReset });
    }
  }, [reset, undoReset, showToast]);

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
      const piiText = res.pii_detected ? formatPii(res.pii_counts) : "";
      setAttachments((a) => [...a, {
        filename: file.name, ocr_engine: res.engine || "tesseract",
        text: res.text.slice(0, MAX_OCR_CHARS), n_chars: res.n_chars || res.text.length,
        pii: piiText || null,
      }]);
      // KVKK şeffaflık: belgede kişisel veri varsa kullanıcıyı bilgilendir.
      showToast(piiText
        ? `Belge eklendi · Dikkat: belgenizde ${piiText} tespit edildi (sorunuzla birlikte işlenecek).`
        : `Belge eklendi: ${file.name} (${res.n_chars || res.text.length} karakter)`);
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
  const showSrcPill = srcTurn && ["sources", "drafting", "verifying", "final"].includes(srcTurn.phase) && srcCount > 0;

  return (
    <div className="sor-app">
      {/* a11y: klavye kullanıcısı sidebar'ı atlayıp doğrudan sohbete geçebilsin */}
      <a href="#sor-main" className="skip-link">İçeriğe geç</a>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
        onNew={onNewChat}
        currentTitle={turns[0]?.question || null}
      />
      <input ref={fileRef} type="file" accept="image/*,application/pdf" hidden onChange={onFile} />

      <div className="main-col" id="sor-main">
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
              {/* streaming=true iken gold ripple — 60fps.design D2 */}
              <span className={"dot" + (busy ? " streaming" : "")}></span>
              {domain}{domainLow ? " · belirsiz" : ""}
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
                {/* Trust signals — abtest.design D11, +44% güven etkisi */}
                <div className="trust-signals">
                  <span><Icon.check />Yargıtay kararlarıyla doğrulandı</span>
                  <span><Icon.check />Kaynaklar açık ve izlenebilir</span>
                  <span><Icon.check />Sıfır uydurma taahhüdü</span>
                </div>
                <div className="cg-input-wrap">
                  <CGInput
                    value={input} onChange={setInput} onSubmit={doAsk} busy={false} autoFocus
                    onAttach={onAttach} attachCount={attachments.length}
                    wantDilekce={wantDilekce} onToggleDilekce={() => setWantDilekce((v) => !v)}
                    onStop={stop}
                  />
                  {/* daisyUI kbd deseni — klavye kısayolu ipuçları (keşfedilebilirlik) */}
                  <div className="kbd-hints">
                    <span><kbd className="kbd">Enter</kbd> gönder</span>
                    <span><kbd className="kbd">Shift</kbd>+<kbd className="kbd">Enter</kbd> yeni satır</span>
                  </div>
                  {attachments.length > 0 && <AttachRow attachments={attachments} onClear={() => setAttachments([])} />}
                  <div className="domain-cards">
                    {DOMAIN_CARDS.map((d, i) => {
                      const I = Icon[d.icon];
                      return (
                        <button
                          className="domain-card" key={d.label}
                          style={{ animationDelay: i * 60 + "ms" }}
                          onClick={() => doAsk(d.q)}
                        >
                          <span className="dc-ic"><I /></span>
                          <span className="dc-tx">
                            <span className="dc-label">{d.label} Hukuku</span>
                            <span className="dc-q">{d.q}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <React.Fragment>
                <div
                  className="chat-scroll" ref={scrollRef} onScroll={onChatScroll}
                  role="log" aria-live="polite" aria-relevant="additions text" aria-label="Sohbet akışı"
                >
                  <div className="chat-inner">
                    {turns.map((turn) => (
                      <TurnView
                        key={turn.key} turn={turn}
                        onJump={jumpToSource}
                        onRetry={() => setInput(retryLast())}
                        onReask={ask}
                        onEdit={(newText) => editFrom(turn.key, newText)}
                        onClarifyPick={pickClarify}
                        onToast={showToast}
                        onDownloadDilekce={onDownloadDilekce}
                      />
                    ))}
                  </div>
                </div>
                {!atBottom && (
                  <button className="scroll-bottom" onClick={() => scrollToBottom(true)} aria-label="En alta in" title="En alta in">
                    <Icon.chevron />
                  </button>
                )}
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

      <div className={"sheet-backdrop" + (sheetOpen ? " open" : "")} onClick={() => setSheetOpen(false)} aria-hidden="true"></div>
      <aside
        className={"source-panel drawer " + (sheetOpen ? "open" : "closed")} ref={panelRef}
        role="dialog" aria-modal="true" aria-label="Kaynaklar paneli" aria-hidden={!sheetOpen}
      >
        <div className="drawer-head">
          <h3>Kaynaklar</h3>
          <button className="icon-btn" onClick={() => setSheetOpen(false)} aria-label="Kaynaklar panelini kapat"><Icon.plus style={{ transform: "rotate(45deg)" }} /></button>
        </div>
        <div className="source-inner" style={{ paddingTop: 6 }}>
          <SourcePanelBody turn={srcTurn} flash={flash} registerRef={(n, el) => { srcRefs.current[n] = el; }} />
        </div>
      </aside>

      {beam && <BeamLayer beam={beam} />}
      {/* a11y (§8): kalıcı canlı bölge — ekran okuyucu tüm toast'ları (OCR,
          kopyala, dilekçe, PII uyarısı) duyurur. Görsel toast ayrı render edilir. */}
      <div className="sr-only" role="status" aria-live="polite">{toast?.msg || ""}</div>
      {toast && (
        <div className="toast" aria-hidden="true">
          <span className="toast-msg">{toast.msg}</span>
          {toast.action && (
            <button
              className="toast-action"
              onClick={() => { toast.action.onClick(); dismissToast(); }}
            >
              {toast.action.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- attachment chips ---------- */
function AttachRow({ attachments, onClear }) {
  return (
    <div className="attach-row">
      {attachments.map((a, i) => (
        <span className={"attach-chip" + (a.pii ? " has-pii" : "")} key={i} title={a.pii ? `Belgenizde ${a.pii} tespit edildi` : a.filename}>
          <Icon.image style={{ width: 13, height: 13 }} />{a.filename}
          {a.pii && <span className="pii-flag" aria-label={`Kişisel veri: ${a.pii}`}>● kişisel veri</span>}
        </span>
      ))}
      <button className="attach-clear" onClick={onClear}>temizle</button>
    </div>
  );
}

/* ---------- one conversation turn ---------- */
function TurnView({ turn, onJump, onRetry, onReask, onEdit, onClarifyPick, onToast, onDownloadDilekce }) {
  const d = turn.data;
  const p = turn.phase;
  const streaming = ["triage", "sources", "drafting", "verifying"].includes(p);
  return (
    <React.Fragment>
      <UserBubble text={turn.question} onEdit={onEdit} />
      <div className="assistant-row">
        <span className="ava"><Icon.scale /></span>
        <div className="assistant-body">
          {streaming && <StreamStepper phase={p} customLabel={d.domain ? `Soru sınıflandırıldı — ${d.domain}` : null} />}
          {["drafting", "verifying"].includes(p) && <ThinkingSkeleton />}

          {d.kind === "clarify" && p === "clarify" && (
            <ClarifyCard data={d.clarify} onPick={onClarifyPick} />
          )}

          {d.risk && p === "final" && <RiskWarning text={d.risk.text} />}

          {p === "final" && d.answer && (
            <React.Fragment>
              <AnswerCard answer={d.answer} sources={d.sources ?? []} onJump={onJump} />
              <EvidenceStats confidence={d.answer.confidence} sourceCount={(d.sources ?? []).length} claims={d.claims} />
              <AgentTrace
                claims={d.claims} debateNotes={d.debateNotes}
                retryCount={d.retryCount} sourceCount={d.sources.length}
                domain={d.domain}
              />
              {d.prediction && <PredictionCard prediction={d.prediction} />}
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
  const loading = ["sources", "drafting", "verifying"].includes(p);
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
