/* ADALET /sor — ana uygulama (gerçek backend'e bağlı).
   Prototip tasarımı korunur; mock motor yerine useChat (SSE). */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Icon, SB_NAV, CIVIL_DOMAINS } from "./components/icons.jsx";
import {
  RiskWarning, DisclaimerBar, SourceCard, SourceSkeleton, StreamStepper,
} from "./components/ui.jsx";
import { AnswerCard, RelatedCases, RejectCard, ClarifyCard, UserBubble, SmallTalkBubble, DraftStreamBubble } from "./components/cards.jsx";
import { AgentTrace, PredictionCard, EvidenceStats, QuickTyping } from "./components/panels.jsx";
import { UserMenu } from "./components/UserMenu.jsx";
import { ConversationList } from "./components/ConversationList.jsx";
import { Modal } from "./components/Modal.jsx";
import { SearchPanel, LibraryPanel, FilesPanel } from "./components/historyPanels.jsx";
import { postFeedback, synthesizeTTS, ocrUpload, downloadDilekce } from "./lib/api.js";
import { useChat } from "./hooks/useChat.js";
import { useVoiceRecorder } from "./hooks/useVoiceRecorder.js";
import { usePrefs } from "./hooks/usePrefs.js";
import { useConversations } from "./hooks/useConversations.js";
import { DEMO_TURN } from "./lib/demoTurn.js";

// Önizleme modu: ?preview=1 → backend olmadan tam cevap UI'ı (tasarım QA + demo).
// YALNIZ DEV'de (Root.jsx ile aynı): production'da ?preview=1 ile demo moduna
// düşüp saveConversation'ı atlamak YASAK (veri kaybı/bypass). prod'da daima false.
const PREVIEW = import.meta.env.DEV
  && typeof window !== "undefined" && new URLSearchParams(window.location.search).has("preview");

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
import { addFileSb } from "./lib/supabaseData.js";
import { Toaster, toast as sonnerToast } from "sonner";
import { ShimmerButton } from "./components/ui/shimmer-button.jsx";
import { AnimatedGradientText } from "./components/ui/animated-gradient-text.jsx";
import "./styles/sor.css";
import "./styles/sor-pro.css";
import "./styles/app-extra.css";
import "./styles/agent-flow.css";
import "./styles/account.css";
import "./styles/history.css";

/* ---------- ChatGPT-style input pill ---------- */
function CGInput({ value, onChange, onSubmit, busy, autoFocus, onAttachPhoto, onAttachDoc, attachCount, wantDilekce, onToggleDilekce, onStop }) {
  const ref = useRef(null);
  // "+" → Fotoğraf / Belge (PDF/Word) seçim menüsü.
  const [attachMenu, setAttachMenu] = useState(false);
  const attachMenuRef = useRef(null);
  const attachBtnRef = useRef(null);
  useEffect(() => {
    if (!attachMenu) return undefined;
    const onDoc = (e) => {
      if (attachMenuRef.current && !attachMenuRef.current.contains(e.target)) setAttachMenu(false);
    };
    const onKey = (e) => {
      // Esc → kapat + odağı tetikleyici butona geri ver (ARIA menu kuralı).
      if (e.key === "Escape") { setAttachMenu(false); attachBtnRef.current?.focus(); }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [attachMenu]);
  // Sesli giriş (#7): mic-kayıt → Whisper STT → transkripti input'a yaz. Buton input boşken görünür.
  const voice = useVoiceRecorder({ onTranscript: (t) => onChange(t) });
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
      <div className="cg-attach" ref={attachMenuRef}>
        <button
          ref={attachBtnRef}
          className="cg-round"
          aria-label="Fotoğraf veya belge ekle"
          aria-haspopup="menu"
          aria-expanded={attachMenu}
          onClick={() => setAttachMenu((o) => !o)}
          title="Fotoğraf veya belge ekle"
        >
          <Icon.plus />
          {attachCount > 0 && <span className="attach-badge">{attachCount}</span>}
        </button>
        {attachMenu && (
          <div className="attach-menu" role="menu">
            <button
              type="button" role="menuitem" className="attach-menu-item" autoFocus
              onClick={() => { setAttachMenu(false); onAttachPhoto?.(); }}
            >
              <Icon.image style={{ width: 16, height: 16 }} />Fotoğraf
            </button>
            <button
              type="button" role="menuitem" className="attach-menu-item"
              onClick={() => { setAttachMenu(false); onAttachDoc?.(); }}
            >
              <Icon.file style={{ width: 16, height: 16 }} />Belge (PDF / Word)
            </button>
          </div>
        )}
      </div>
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
        ) : (hasText && voice.state === "idle") ? (
          <ShimmerButton
            onClick={submit}
            aria-label="Gönder"
            background="var(--accent)"
            shimmerColor="#f4ddbb"
            shimmerDuration="2.4s"
            borderRadius="999px"
            className="cg-send go !px-0 !py-0 !border-0"
          >
            <Icon.send />
          </ShimmerButton>
        ) : (
          <button
            className={"cg-send voice" + (voice.state !== "idle" ? " on" : "")}
            onClick={() => { ref.current?.focus(); voice.toggle(); }}
            disabled={!voice.supported || voice.state === "transcribing"}
            aria-label={voice.state === "recording" ? "Kaydı durdur" : "Sesli sor (mikrofon)"}
            aria-pressed={voice.state === "recording"}
            title={
              !voice.supported ? "Tarayıcı ses kaydını desteklemiyor"
                : voice.state === "recording" ? "Kaydı durdur"
                : voice.state === "transcribing" ? "Metne çevriliyor…"
                : "Sesli sor"
            }
          >
            {voice.state === "recording" ? <Icon.stop />
              : voice.state === "transcribing" ? <Icon.wave />
              : <Icon.mic />}
          </button>
        )}
      </div>
      {voice.error && (
        <span className="cg-voice-err" role="status" aria-live="polite">{voice.error}</span>
      )}
    </div>
  );
}

const NAV_TITLES = { search: "Sohbetlerde ara", library: "Kaynaklar", files: "Dosyalarım" };

/* ---------- Sidebar ---------- */
function Sidebar({ collapsed, onToggle, onNew, onNav, conversations, activeConvId, onSelectConv, onDeleteConv, userMenu }) {
  const NAV_ACTION = {
    new: onNew,
    search: () => onNav("search"),
    library: () => onNav("library"),
    projects: () => onNav("files"),
  };
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
            <button
              className={"sb-item" + (n.id === "new" ? " primary" : "")}
              key={n.id}
              onClick={NAV_ACTION[n.id]}
            >
              <I />{n.label}
            </button>
          );
        })}
      </nav>
      <div className="sb-section-label">Sohbet geçmişi</div>
      <div className="sb-list">
        <ConversationList
          conversations={conversations} activeId={activeConvId}
          onSelect={onSelectConv} onDelete={onDeleteConv}
        />
      </div>
      {userMenu}
    </aside>
  );
}

export default function App({ auth }) {
  const authUser = auth?.user || null;
  const onLogout = auth?.logout || null;
  const { turns: chatTurns, ask, stop, pickClarify, retryLast, editFrom, reset, loadConversation, busy, conversationId } = useChat();
  const { prefs, setPref, toggleDomain } = usePrefs();
  const { conversations, saveConversation, removeConversation, getConversation, search, allSources, allFiles } = useConversations();
  const turns = PREVIEW ? [DEMO_TURN] : chatTurns;
  const [input, setInput] = useState("");
  const [sheetOpen, setSheetOpen] = useState(false);
  // Yan kaynak-panelinde gösterilecek turn (per-cevap). null → en son cevap (srcTurn).
  const [sheetTurn, setSheetTurn] = useState(null);
  // Yan panel modu: "sources" (kanun+karar) | "cases" (yalnız ilgili mahkeme kararları).
  const [sheetMode, setSheetMode] = useState("sources");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 760);
  const [flash, setFlash] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [wantDilekce, setWantDilekce] = useState(false);
  const [toast, setToast] = useState(null);
  const [atBottom, setAtBottom] = useState(true);
  const [navPanel, setNavPanel] = useState(null); // null | "search" | "library" | "files"

  const scrollRef = useRef(null);
  const panelRef = useRef(null);
  const srcRefs = useRef({});
  // Ayrı gizli input'lar — accept'i çalışma anında mutasyona uğratmak yerine (race + React
  // bypass) her tip için sabit-accept'li kendi input'u (Fotoğraf vs Belge).
  const photoRef = useRef(null);
  const docRef = useRef(null);
  const sessionFilesRef = useRef([]); // bu sohbette yüklenen belgeler (Dosyalarım)
  const savedSigRef = useRef(null);   // aynı durumu tekrar kaydetme (persist dedup)

  const last = turns[turns.length - 1];
  const started = turns.length > 0;

  // Boş ekran kartları: tercih edilen alanlar öne (usePrefs); ilk 4 gösterilir.
  // Tercih yoksa CIVIL_DOMAINS doğal sırası (tüketici/iş/kira/icra…).
  const heroCards = useMemo(() => {
    const pref = prefs.preferredDomains;
    if (!pref.length) return CIVIL_DOMAINS.slice(0, 4);
    const ordered = [...CIVIL_DOMAINS].sort((a, b) => {
      const ai = pref.indexOf(a.id), bi = pref.indexOf(b.id);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
    return ordered.slice(0, 4);
  }, [prefs.preferredDomains]);

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
    // sr-only canlı bölge (ekran okuyucu) — görsel toast artık Sonner (animasyonlu, yığılır).
    clearTimeout(toastTimer.current);
    setToast({ msg, action });
    toastTimer.current = setTimeout(() => setToast(null), action ? 6000 : 3200);
    sonnerToast(msg, action
      ? { duration: 6000, action: { label: action.label, onClick: action.onClick } }
      : { duration: 3200 });
  }, []);
  const dismissToast = useCallback(() => {
    clearTimeout(toastTimer.current); setToast(null); sonnerToast.dismiss();
  }, []);

  // "Yeni sohbet": görünümü temizle (geçmiş KALICI — silmez).
  const onNewChat = useCallback(() => {
    sessionFilesRef.current = [];
    savedSigRef.current = null;
    if (reset()) {
      showToast("Yeni sohbet başlatıldı");
    }
  }, [reset, showToast]);

  // Geçmiş sohbeti yükle (sidebar) → useChat'e bas + oturum dosyalarını geri yükle.
  const onSelectConv = useCallback((conv) => {
    const rec = getConversation(conv.id) || conv;
    loadConversation(rec);
    sessionFilesRef.current = rec.files || [];
    // SADECE-AÇMA üste çıkarMAMALI: savedSigRef'i kaydetme-effect'inin (turns değişince)
    // hesaplayacağı sig ile BİREBİR eşitle → yüklenen sohbet yeniden kaydedilmez, updatedAt
    // bump'lanmaz, sıra korunur. Yeni soru sorulunca turns.length artar → sig değişir → kaydedilir
    // → o zaman üste çıkar (son-aktivite sırası, son-açılma değil).
    const _t = rec.turns || [];
    const _lastPhase = _t.length ? (_t[_t.length - 1].phase || "") : "";
    savedSigRef.current = `${rec.id}:${_t.length}:${_lastPhase}`;
    setSheetOpen(false);
    setNavPanel(null);
    if (window.innerWidth < 760) setSidebarCollapsed(true);
  }, [getConversation, loadConversation]);

  // Sohbeti sil → aktif olanı siliyorsa görünümü de temizle.
  const onDeleteConv = useCallback((id) => {
    removeConversation(id);
    if (id === conversationId) { sessionFilesRef.current = []; reset(); }
    showToast("Sohbet silindi");
  }, [removeConversation, conversationId, reset, showToast]);

  // Tamamlanan turu geçmişe kaydet (kalıcı): busy düşünce + son turn terminal olunca.
  useEffect(() => {
    if (PREVIEW || busy || !conversationId || !turns.length) return;
    const lastTurn = turns[turns.length - 1];
    if (!["final", "reject", "clarify"].includes(lastTurn.phase)) return;
    const sig = `${conversationId}:${turns.length}:${lastTurn.phase}`;
    if (savedSigRef.current === sig) return; // aynı durumu tekrar kaydetme
    savedSigRef.current = sig;
    const title = (turns[0]?.question || "Sohbet").slice(0, 80);
    const domain = lastTurn.data?.domain || (turns.find((t) => t.data?.domain)?.data?.domain || "");
    const trimmed = turns.map((t) => ({ question: t.question, phase: t.phase, data: t.data }));
    saveConversation(conversationId, { title, domain, turns: trimmed, files: sessionFilesRef.current });
  }, [busy, conversationId, turns, saveConversation]);

  const doAsk = useCallback((text) => {
    const opts = { wantDilekce, attachments: attachments.length ? attachments : undefined };
    if (attachments.length) {
      sessionFilesRef.current = [
        ...sessionFilesRef.current,
        ...attachments.map((a) => ({
          filename: a.filename, ocr_engine: a.ocr_engine, n_chars: a.n_chars, pii: a.pii,
        })),
      ];
    }
    ask(text, opts);
    setInput("");
    setAttachments([]);
    setSheetOpen(false);
  }, [ask, wantDilekce, attachments]);

  /* ---------- OCR upload ---------- */
  // "+" menüsü: Fotoğraf → görsel input; Belge → PDF/Word input (her biri sabit accept).
  const onAttachPhoto = () => photoRef.current?.click();
  const onAttachDoc = () => docRef.current?.click();
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    showToast("Belge okunuyor (OCR)…");
    try {
      const res = await ocrUpload(file);
      if (!res.text || res.text.length < 5) {
        // Backend spesifik neden döndürdüyse (şifreli/bozuk PDF, motor yok) onu göster.
        showToast(res.error || "Belgeden metin çıkarılamadı. Belge boş veya okunamıyor olabilir.");
        return;
      }
      const engine = res.engine || "rapidocr";
      const piiText = res.pii_detected ? formatPii(res.pii_counts) : "";
      setAttachments((a) => [...a, {
        filename: file.name, ocr_engine: engine,
        text: res.text.slice(0, MAX_OCR_CHARS), n_chars: res.n_chars || res.text.length,
        pii: piiText || null,
        lowConf: !!res.low_confidence,  // #20: düşük OCR güveni → kullanıcıyı metni kontrol etmeye uyar
      }]);
      // "Dosyalarım" metadata → Supabase (best-effort; oturumsuzda no-op, metin saklanmaz).
      addFileSb({
        conversation_id: conversationId || "", filename: file.name,
        ocr_engine: engine, n_chars: res.n_chars || res.text.length,
        pii_flag: !!piiText,
      });
      // Şeffaflık: düşük güven + taranmış-belge diakritik kaybı uyarısı.
      const lowNote = res.low_confidence
        ? " · OCR güveni düşük olabilir — eklenen metni kontrol edin."
        : "";
      // Yalnız LOKAL OCR (rapidocr/tesseract) Türkçe işaret (ç/ş/ğ) düşürebilir → uyar.
      // pdf-text (dijital), docx-text (Word) ve openai-vision (bulut) kusursuz → uyarı yok.
      const isLossyOcr = engine.includes("rapidocr") || engine.includes("tesseract");
      const scanNote = isLossyOcr
        ? " · OCR ile okundu — Türkçe işaretler eksik olabilir, metni kontrol edin."
        : "";
      // Çok-sayfa PDF bilgisi.
      const pageNote = res.page_count > 1 ? ` · ${res.page_count} sayfa işlendi` : "";
      showToast((piiText
        ? `Belge eklendi · Dikkat: belgenizde ${piiText} tespit edildi (sorunuzla birlikte işlenecek).`
        : `Belge eklendi: ${file.name} (${res.n_chars || res.text.length} karakter)`) + pageNote + lowNote + scanNote);
    } catch (err) {
      // ocrUpload artık backend `detail` mesajını fırlatıyor (415/413/400) — onu göster.
      showToast(err?.message || "OCR başarısız — backend çalışıyor mu?");
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
  // Animasyon timer'larını izle: hızlı ardışık tıklamada önceki timer'lar yeni animasyonu
  // ortasından sıfırlamasın; unmount'ta da kalmış timer silinmiş state'i güncellemesin.
  const beamTimersRef = useRef([]);
  const clearBeamTimers = useCallback(() => {
    beamTimersRef.current.forEach(clearTimeout);
    beamTimersRef.current = [];
  }, []);
  const jumpToSource = useCallback((n, citeEl) => {
    clearBeamTimers();
    const t = beamTimersRef.current;
    const startRect = citeEl ? citeEl.getBoundingClientRect() : null;
    setSheetOpen(true);
    setFlash(n);
    t.push(setTimeout(() => {
      const el = srcRefs.current[n];
      const sc = panelRef.current;
      if (el && sc) sc.scrollTo({ top: el.offsetTop - 16, behavior: "smooth" });
      t.push(setTimeout(() => {
        const card = document.querySelector('[data-src-id="' + n + '"]');
        if (startRect && card) {
          const er = card.getBoundingClientRect();
          setBeam({ x1: startRect.right, y1: startRect.top + startRect.height / 2,
            x2: er.left + 10, y2: er.top + 24, key: Date.now() });
        }
      }, 240));
    }, 340));
    t.push(setTimeout(() => setFlash(null), 1900));
    t.push(setTimeout(() => setBeam(null), 1700));
  }, [clearBeamTimers]);
  useEffect(() => clearBeamTimers, [clearBeamTimers]); // unmount temizliği

  /* ---------- source panel content ---------- */
  const srcTurn = useMemo(() => {
    for (let k = turns.length - 1; k >= 0; k--) {
      const d = turns[k].data;
      if ((d.kind === "answer" && turns[k].phase !== "triage") || d.kind === "reject") return turns[k];
    }
    return null;
  }, [turns]);


  return (
    <div className="sor-app">
      {/* a11y: klavye kullanıcısı sidebar'ı atlayıp doğrudan sohbete geçebilsin */}
      <a href="#sor-main" className="skip-link">İçeriğe geç</a>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
        onNew={onNewChat}
        onNav={setNavPanel}
        conversations={conversations}
        activeConvId={conversationId}
        onSelectConv={onSelectConv}
        onDeleteConv={onDeleteConv}
        userMenu={
          <UserMenu
            prefs={prefs} setPref={setPref} toggleDomain={toggleDomain}
            onClearSession={onNewChat} onAsk={doAsk} showToast={showToast}
            user={authUser} onLogout={onLogout}
          />
        }
      />
      <input ref={photoRef} type="file" accept="image/*" hidden aria-hidden="true" tabIndex={-1} onChange={onFile} />
      <input ref={docRef} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden aria-hidden="true" tabIndex={-1} onChange={onFile} />

      <div className="main-col" id="sor-main">
        {sidebarCollapsed && (
          <button className="float-toggle" onClick={() => setSidebarCollapsed(false)} aria-label="Kenar çubuğunu aç"><Icon.panel /></button>
        )}

        <header className="main-head">
          <button className="model" style={sidebarCollapsed ? { marginLeft: 40 } : undefined}>
            ADALET <span className="sub">5.0</span> <Icon.chevron />
          </button>
          {/* Global domain çipi kaldırıldı: yalnız EN SON cevabın domain'ini gösteriyordu →
              çok-konulu sohbette yanıltıcı (ağaç=tapu + kamulaştırma=idari aynı sohbette). */}
          <div className="spacer"></div>
          {/* Global "Kaynaklar" pill kaldırıldı — her cevabın kendi "Kaynak ›" butonu var. */}
        </header>

        <div className="panels">
          <section className="chat-panel">
            {!started ? (
              <div className="cg-hero">
                <h1 className="cg-greet">
                  {(authUser?.name || prefs.displayName || "").trim()
                    ? <>Nasıl yardımcı olabilirim, <AnimatedGradientText colorFrom="#9e6a43" colorTo="#d9a866" speed={1.4}>{(authUser?.name || prefs.displayName).trim().split(/\s+/)[0]}</AnimatedGradientText>?</>
                    : <>Bugün size nasıl <AnimatedGradientText colorFrom="#9e6a43" colorTo="#d9a866" speed={1.4}>yardımcı</AnimatedGradientText> olabilirim?</>}
                </h1>
                {/* Trust signals — abtest.design D11, +44% güven etkisi */}
                <div className="trust-signals">
                  <span><Icon.check />Yargıtay kararlarıyla doğrulandı</span>
                  <span><Icon.check />Kaynaklar açık ve izlenebilir</span>
                  <span><Icon.check />Sıfır uydurma taahhüdü</span>
                </div>
                <div className="cg-input-wrap">
                  <CGInput
                    value={input} onChange={setInput} onSubmit={doAsk} busy={false} autoFocus
                    onAttachPhoto={onAttachPhoto} onAttachDoc={onAttachDoc} attachCount={attachments.length}
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
                    {heroCards.map((d, i) => {
                      const I = Icon[d.icon];
                      return (
                        <button
                          className="domain-card" key={d.id}
                          style={{ animationDelay: i * 60 + "ms" }}
                          onClick={() => doAsk(d.ex)}
                        >
                          <span className="dc-ic"><I /></span>
                          <span className="dc-tx">
                            <span className="dc-label">{d.label} Hukuku</span>
                            <span className="dc-q">{d.ex}</span>
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
                        onOpenSources={(t) => { setSheetMode("sources"); setSheetTurn(t); setSheetOpen(true); }}
                        onOpenCases={(t) => { setSheetMode("cases"); setSheetTurn(t); setSheetOpen(true); }}
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
                      onAttachPhoto={onAttachPhoto} onAttachDoc={onAttachDoc} attachCount={attachments.length}
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
        role="dialog" aria-modal="true"
        aria-label={sheetMode === "cases" ? "İlgili davalar paneli" : "Kaynaklar paneli"}
        aria-hidden={!sheetOpen}
      >
        <div className="drawer-head">
          <div className="drawer-head-tx">
            <h3>{sheetMode === "cases" ? "İlgili Davalar" : "Kaynaklar"}</h3>
            {/* Hangi sorunun kaynakları olduğu net olsun — soru metni başlıkta. */}
            {(sheetTurn || srcTurn)?.question && (
              <p className="drawer-q" title={(sheetTurn || srcTurn).question}>
                “{(sheetTurn || srcTurn).question}”
              </p>
            )}
            {/* Şeffaflık: corpus'tan kaç aday tarandı, kaçı cevaba dayanak oldu. */}
            {sheetMode !== "cases" && (() => {
              const _st = sheetTurn || srcTurn;
              const _used = _st?.data?.sources?.length || 0;
              const _scanned = _st?.data?.scannedCount || 0;
              return _scanned > _used ? (
                <p className="drawer-scan">{_scanned} kaynak tarandı · {_used} tanesi bu cevaba dayanak oldu</p>
              ) : null;
            })()}
          </div>
          <button className="icon-btn" onClick={() => setSheetOpen(false)} aria-label={sheetMode === "cases" ? "İlgili davalar panelini kapat" : "Kaynaklar panelini kapat"}><Icon.plus style={{ transform: "rotate(45deg)" }} /></button>
        </div>
        <div className="source-inner" style={{ paddingTop: 6 }}>
          <SourcePanelBody turn={sheetTurn || srcTurn} mode={sheetMode} flash={flash} registerRef={(n, el) => { srcRefs.current[n] = el; }} />
        </div>
      </aside>

      {navPanel && (
        <Modal title={NAV_TITLES[navPanel]} wide={navPanel !== "files"} onClose={() => setNavPanel(null)}>
          {navPanel === "search" && <SearchPanel search={search} onSelect={onSelectConv} />}
          {navPanel === "library" && (
            <LibraryPanel
              sources={allSources()}
              onSelect={(cid) => { const r = getConversation(cid); if (r) onSelectConv(r); }}
            />
          )}
          {navPanel === "files" && (
            <FilesPanel
              files={allFiles()}
              onSelect={(cid) => { const r = getConversation(cid); if (r) onSelectConv(r); }}
            />
          )}
        </Modal>
      )}

      {beam && <BeamLayer beam={beam} />}
      {/* a11y (§8): kalıcı canlı bölge — ekran okuyucu tüm toast'ları (OCR,
          kopyala, dilekçe, PII uyarısı) duyurur. Görsel toast ayrı render edilir. */}
      <div className="sr-only" role="status" aria-live="polite">{toast?.msg || ""}</div>
      {/* Sonner — animasyonlu, yığılabilir toast; warm-light temaya bağlı (terracotta aksiyon). */}
      <Toaster
        position="bottom-center"
        offset={88}
        gap={10}
        toastOptions={{
          style: {
            background: "var(--surface-strong)",
            color: "var(--text)",
            border: "1px solid var(--border-strong)",
            borderRadius: "13px",
            boxShadow: "var(--shadow-lg)",
            fontFamily: "var(--font-body)",
            fontSize: "14px",
          },
          actionButtonStyle: {
            background: "var(--accent)",
            color: "var(--accent-on)",
            borderRadius: "8px",
            fontWeight: 600,
          },
        }}
      />
    </div>
  );
}

/* ---------- attachment chips ---------- */
export function AttachRow({ attachments, onClear }) {
  return (
    <div className="attach-row">
      {attachments.map((a, i) => (
        <span
          className={"attach-chip" + (a.pii ? " has-pii" : "") + (a.lowConf ? " low-conf" : "")}
          key={i}
          title={
            a.pii ? `Belgenizde ${a.pii} tespit edildi`
              : a.lowConf ? "OCR güveni düşük — eklenen metni kontrol edin"
              : a.filename
          }
        >
          <Icon.image style={{ width: 13, height: 13 }} />{a.filename}
          {a.pii && <span className="pii-flag" aria-label={`Kişisel veri: ${a.pii}`}>● kişisel veri</span>}
          {/* #20: düşük OCR güveni uyarısı — bozuk taramada vatandaş metni gözden geçirsin */}
          {a.lowConf && <span className="lowconf-flag" aria-label="OCR güveni düşük">⚠ düşük OCR güveni</span>}
        </span>
      ))}
      <button className="attach-clear" onClick={onClear}>temizle</button>
    </div>
  );
}

/* ---------- one conversation turn ---------- */
export function TurnView({ turn, onJump, onRetry, onReask, onEdit, onClarifyPick, onToast, onDownloadDilekce, onOpenSources, onOpenCases }) {
  const d = turn.data;
  const p = turn.phase;
  const streaming = ["triage", "sources", "drafting", "verifying"].includes(p);
  // Hafif yol (selam/yönlendirme/kapsam-dışı): token akmaz → ağır stepper yerine hafif gösterge.
  const softPath = ["chat", "smalltalk", "redirect", "out_of_scope_sensitive"].includes(d.intent);
  return (
    <React.Fragment>
      <UserBubble text={turn.question} onEdit={onEdit} />
      <div className="assistant-row">
        <span className="ava"><Icon.scale /></span>
        <div className="assistant-body">
          {/* Hafif yol (selam/genel sohbet): chat node Qwen ile CANLI yazar → tokenlar
              geldikçe baloncukta akar (ChatGPT gibi). Token gelmeden hafif "yazıyor". */}
          {streaming && softPath && (
            d.draftText
              ? <SmallTalkBubble text={d.draftText} />
              : <QuickTyping label="Yazıyor" />
          )}
          {/* Hukuki yol: İLK fazdan (triage) itibaren şeffaflık stepper'ı + ilk token
              gelince CANLI taslak baloncuğu. Önceden bu dalda HİÇBİR ŞEY render edilmiyordu
              (ekran boş kalıyordu → "insanlar beklemez"). Artık:
                1) StreamStepper — sınıflandırma→kaynaklar→yazım→doğrulama aşamaları + ilerleme
                   (token öncesi boşlukta bile canlı hareket; lokal model daha hızlı HİSSEDİLİR).
                2) DraftStreamBubble — token'lar geldikçe metin yazılır (ChatGPT hissi), AÇIKÇA
                   "doğrulanacak" rozetiyle. Final gelince doğrulanmış AnswerCard ile DEĞİŞİR
                   (ham taslak düşer → sıfır-halüsinasyon korunur, kullanıcı yine de beklemez). */}
          {streaming && !softPath && (
            <React.Fragment>
              <StreamStepper phase={p} customLabel={d.domain ? `${d.domain} — sorunuz inceleniyor…` : undefined} />
              {d.draftText && (p === "drafting" || p === "verifying") && (
                <DraftStreamBubble text={d.draftText} />
              )}
            </React.Fragment>
          )}

          {p === "smalltalk" && d.smalltalk && (
            <React.Fragment>
              <SmallTalkBubble text={d.smalltalk.text} />
              {/* Hukuki-ipuçlu chat'te backend disclaimers[] doldurur → TEK otorite bar'da
                  göster (gövdeye gömme yok → akış/final tutarlı). Saf selam → liste boş → bar yok. */}
              {d.disclaimers?.length ? <DisclaimerBar items={d.disclaimers} /> : null}
            </React.Fragment>
          )}

          {d.kind === "clarify" && p === "clarify" && (
            <ClarifyCard data={d.clarify} onPick={onClarifyPick} />
          )}

          {d.risk && p === "final" && <RiskWarning text={d.risk.text} />}

          {p === "final" && d.answer && (
            <React.Fragment>
              <AnswerCard answer={d.answer} sources={d.sources ?? []} onJump={onJump} />
              {/* İlgili Kararlar inline GÖSTERİLMEZ (tekrar olmasın): yalnız EvidenceStats'taki
                  "İlgili Kararlar" stat'ına basınca yan panelde açılır (SourcePanelBody cases modu). */}
              <EvidenceStats
                confidence={d.answer.confidence} sourceCount={(d.sources ?? []).length} claims={d.claims}
                onOpenSources={onOpenSources ? () => onOpenSources(turn) : undefined}
                caseCount={(d.relatedCases ?? []).length}
                onOpenCases={onOpenCases ? () => onOpenCases(turn) : undefined}
              />
              <AgentTrace
                claims={d.claims} debateNotes={d.debateNotes}
                retryCount={d.retryCount} sourceCount={(d.sources ?? []).length}
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
                conversationId={d.conversationId}
                onReask={() => onReask(turn.question)}
                onToast={onToast}
              />
              <DisclaimerBar items={d.disclaimers} />
            </React.Fragment>
          )}

          {p === "reject" && (
            <React.Fragment>
              <RejectCard data={d.reject} onRetry={onRetry} />
              {/* CLAUDE.md §2 kırmızı çizgi: reddedilen hukuki yanıt da disclaimer taşır.
                  Smalltalk yolundaki koşullu desenle aynı → transport-hata/"Durduruldu"
                  gibi disclaimers'sız pseudo-reject'lere gereksiz hukuki disclaimer basılmaz;
                  gerçek verify-reject (backend [DISCLAIMER_TR] gönderir) ise daima gösterir. */}
              {d.disclaimers?.length ? <DisclaimerBar items={d.disclaimers} /> : null}
            </React.Fragment>
          )}
        </div>
      </div>
    </React.Fragment>
  );
}

/* ---------- mesaj eylem çubuğu (hover'da belirir): kopyala / yeniden sor / geri bildirim ---------- */
export function MsgActions({ text, conversationId, onReask, onToast }) {
  const [copied, setCopied] = useState(false);
  const [vote, setVote] = useState(null); // "up" | "down" | null
  // Sesli okuma (#7): cevabı yerel Piper TTS ile seslendir → görme/okuma engelli erişimi
  // (Teknofest İnsanlık-Yararına). State: idle → loading → playing. Tekrar tıklayınca durdurur.
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => () => {
    // Bileşen kalkarken çalan sesi durdur + URL'i serbest bırak (sızıntı önle).
    const a = audioRef.current;
    if (a) { a.pause(); if (a.src) URL.revokeObjectURL(a.src); }
  }, []);

  const speak = async () => {
    if (speaking) {
      audioRef.current?.pause();
      setSpeaking(false);
      return;
    }
    try {
      setSpeaking(true);
      const blob = await synthesizeTTS(text);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => { setSpeaking(false); URL.revokeObjectURL(url); };
      audio.onerror = () => { setSpeaking(false); URL.revokeObjectURL(url); };
      await audio.play();
    } catch {
      setSpeaking(false);
      onToast?.("Sesli okuma şu an kullanılamıyor.");
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      onToast?.("Kopyalanamadı — tarayıcı izni gerekebilir.");
    }
  };
  // Geri bildirim backend'e kaydedilir (anonimleştirilmiş: principal_sub_hash, ham veri yok).
  // Best-effort: optimistik UX (toast hemen), ağ çağrısı arka planda — hata kullanıcıyı durdurmaz.
  const sendVote = (v) => {
    setVote(v);
    onToast?.(v === "up" ? "Teşekkürler — geri bildiriminiz alındı." : "Teşekkürler — bunu iyileştireceğiz.");
    postFeedback({ conversationId, rating: v }).catch(() => { /* sessiz: feedback kritik değil */ });
  };

  return (
    <div className="msg-actions" role="group" aria-label="Yanıt eylemleri">
      <button className="msg-action" onClick={copy} title="Yanıtı kopyala" aria-label="Yanıtı kopyala">
        {copied ? <Icon.check /> : <Icon.copy />}<span>{copied ? "Kopyalandı" : "Kopyala"}</span>
      </button>
      <button className="msg-action" onClick={onReask} title="Aynı soruyu yeniden sor" aria-label="Yeniden sor">
        <Icon.refresh /><span>Yeniden sor</span>
      </button>
      <button
        className={"msg-action" + (speaking ? " on" : "")}
        onClick={speak}
        title={speaking ? "Sesli okumayı durdur" : "Cevabı sesli dinle"}
        aria-label={speaking ? "Sesli okumayı durdur" : "Cevabı sesli dinle"}
        aria-pressed={speaking}
      >
        {speaking ? <Icon.stop /> : <Icon.volume />}<span>{speaking ? "Durdur" : "Dinle"}</span>
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
function SourcePanelBody({ turn, mode = "sources", flash, registerRef }) {
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

  // "Davalar" modu: bu cevabın konusuyla ilgili emsal mahkeme kararları (RelatedCases,
  // onJump'sız → statik başlık + "tam metni" linki). Boşsa dürüst boş-durum.
  if (mode === "cases") {
    const cases = d.relatedCases || [];
    if (!cases.length) {
      return (
        <div className="source-empty">
          <Icon.scale />
          <div>Bu konuyla ilgili emsal mahkeme kararı bu cevapta yer almadı.</div>
        </div>
      );
    }
    return <RelatedCases cases={cases} />;
  }

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
