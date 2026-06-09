/* ADALET /sor — repo-ilhamı paneller (özgün uyarlama).

   - AgentTrace:  vercel/ai-chatbot reasoning.tsx + morphic collapsible-message
                  → ADALET'in 7-ajan + Doğrulama farkını gösteren açılır şeffaflık
                  paneli (claims + debate notes). Kimsede yok; jüri/yarışma "wow".
   - PredictionCard: 8. ajan (Tahmin) — geçmiş Yargıtay'a dayalı istatistiksel
                  tahmin. Disclaimer ZORUNLU (mahkeme garantisi değil).
   - ThinkingSkeleton: vercel shimmer — draft hazırlanırken cevabın yerini tutar.
   - EvidenceStats: daisyUI `stat` deseni (elle-CSS) → cevabın kanıt özetini
                  taranabilir stat-bloklar olarak gösterir (Güven · Kaynak · İddia). */
import React, { useState, useEffect, useId } from "react";
import { Icon } from "./icons.jsx";

/** %0→value ease-out-cubic sayaç (reduced-motion saygılı). */
function useCountUp(value) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const reduce = typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setN(value); return; }
    let t0 = null;
    const dur = 900;
    const tick = (t) => {
      if (!t0) t0 = t;
      const p = Math.min((t - t0) / dur, 1);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    };
    const id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [value]);
  return n;
}

/* ---------- Kanıt özeti — daisyUI stat deseni (Güven · Kaynak · İddia) ---------- */
export function EvidenceStats({ confidence, sourceCount, claims }) {
  const conf = useCountUp(confidence);
  const list = claims || [];
  const verified = list.filter((c) => c.verified).length;
  const total = list.length;
  const mid = confidence < 70;
  return (
    <div className="ev-stats" role="group" aria-label="Kanıt özeti">
      <div className={"ev-stat" + (mid ? " mid" : "")}>
        <div className="ev-val">%{conf}</div>
        <div className="ev-label">Güven</div>
        <div className="ev-bar" aria-hidden="true"><span style={{ width: confidence + "%" }}></span></div>
      </div>
      <div className="ev-divider" aria-hidden="true"></div>
      <div className="ev-stat">
        <div className="ev-val">{sourceCount}</div>
        <div className="ev-label">Kaynak</div>
      </div>
      {total > 0 && (
        <>
          <div className="ev-divider" aria-hidden="true"></div>
          <div className="ev-stat">
            <div className="ev-val">{verified}<span className="ev-sub">/{total}</span></div>
            <div className="ev-label">Doğrulanan iddia</div>
          </div>
        </>
      )}
    </div>
  );
}

/* ---------- Ajan-izi / doğrulama şeffaflık paneli (açılır) ---------- */
export function AgentTrace({ claims, debateNotes, retryCount, sourceCount, domain }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();  // a11y (#37): toggle ↔ açılan bölge ilişkilendirmesi (aria-controls)
  const list = claims || [];
  const total = list.length;
  const okCount = list.filter((c) => c.verified).length;

  // Gösterilecek bir şey yoksa render etme (DRY/temizlik).
  if (!total && !debateNotes) return null;

  const summary = total > 0
    ? `${okCount}/${total} iddia kaynakla doğrulandı`
    : `${sourceCount || 0} kaynak incelendi`;

  // daisyUI timeline + Lucide ayırt edici ikonlar → 7-ajan pipeline'ı.
  const stages = [
    { label: "Triaj Ajanı", icon: "tag", detail: domain ? `Alan belirlendi: ${domain}` : "Soru sınıflandırıldı" },
    { label: "Mevzuat + Emsal", icon: "book", detail: `${sourceCount || 0} kaynak getirildi (kanun + Yargıtay)` },
    total > 0 && { label: "Doğrulama Ajanı", icon: "shield", detail: `${okCount}/${total} iddia kaynakla eşleşti` },
    debateNotes && { label: "Tartışma Ajanı", icon: "users", detail: "Ajan görüşleri karşılaştırıldı" },
    { label: "Sonuç", icon: "circleCheck", detail: retryCount > 0 ? `Cevap üretildi (${retryCount} yineleme sonrası)` : "Cevap üretildi" },
  ].filter(Boolean);

  return (
    <div className={"agent-trace" + (open ? " open" : "")}>
      <button
        className="at-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Ajan ekibi doğrulama dökümü"
      >
        <span className="at-ic"><Icon.scale /></span>
        <span className="at-title">Ajan ekibi nasıl doğruladı</span>
        <span className="at-meta">
          {summary}{retryCount > 0 ? ` · ${retryCount} yineleme` : ""}
        </span>
        <span className="at-chev"><Icon.chevron /></span>
      </button>

      {open && (
        <div className="at-body" id={panelId}>
          {/* Pipeline timeline — hangi ajanların çalıştığı (daisyUI timeline) */}
          <ol className="at-timeline" aria-label="Ajan hattı">
            {stages.map((s, i) => {
              const StageIcon = Icon[s.icon] || Icon.check;
              return (
              <li className="at-tl-item" key={i}>
                <span className="at-tl-marker" aria-hidden="true"><StageIcon /></span>
                <div className="at-tl-tx">
                  <span className="at-tl-label">{s.label}</span>
                  <span className="at-tl-detail">{s.detail}</span>
                </div>
              </li>
              );
            })}
          </ol>

          <div className="at-claims-head">İddia doğrulama dökümü</div>
          {list.map((c, i) => (
            <div className="at-claim" key={i}>
              <span className={"at-badge " + (c.verified ? "ok" : "no")} aria-hidden="true">
                {c.verified ? <Icon.check /> : <Icon.help />}
              </span>
              <div className="at-claim-tx">
                <p>{c.text}</p>
                <div className="at-claim-meta">
                  <span className={"at-status " + (c.verified ? "ok" : "no")}>
                    {c.verified ? `Doğrulandı · %${c.score}` : "Doğrulanamadı"}
                  </span>
                  {(c.citeNums ?? []).length > 0 && (
                    <span className="at-cites">Kaynak {c.citeNums.join(", ")}</span>
                  )}
                </div>
                {c.reason && <p className="at-reason">{c.reason}</p>}
              </div>
            </div>
          ))}
          {debateNotes && (
            <div className="at-debate">
              <span className="at-debate-lbl">Tartışma Ajanı notu</span>
              <p>{debateNotes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- Tahmin kartı (8. ajan) ---------- */
const PRED_LABEL = {
  kazandi: "Geçmiş kararlarda benzer davalar çoğunlukla LEHE sonuçlanmış",
  kaybetti: "Geçmiş kararlarda benzer davalar çoğunlukla ALEYHE sonuçlanmış",
  kismi: "Benzer davalar kısmen lehe sonuçlanmış",
  belirsiz: "Yeterli/uyumlu emsal sinyali yok — tahmin belirsiz",
};
const PRED_SHORT = { kazandi: "Lehe eğilim", kaybetti: "Aleyhe eğilim", kismi: "Kısmi", belirsiz: "Belirsiz" };
const PRED_TONE = { kazandi: "ok", kaybetti: "no", kismi: "warn", belirsiz: "neutral" };

export function PredictionCard({ prediction: p }) {
  if (!p) return null;
  const tone = PRED_TONE[p.verdictClass] || "neutral";
  const pct = p.confidence;
  return (
    <div className={"pred-card tone-" + tone}>
      <div className="pred-head">
        <span className="pred-ic"><Icon.scale /></span>
        <div className="pred-head-tx">
          <div className="pred-tag">Tahmini sonuç · {PRED_SHORT[p.verdictClass] || "—"}</div>
          <div className="pred-label">{PRED_LABEL[p.verdictClass] || "Tahmini sonuç"}</div>
        </div>
        {p.verdictClass !== "belirsiz" && <div className="pred-pct">%{pct}</div>}
      </div>

      {p.verdictClass !== "belirsiz" && (
        <div className="pred-bar"><span style={{ width: pct + "%" }}></span></div>
      )}

      {p.reasoning && <p className="pred-reason">{p.reasoning}</p>}

      {p.similarCaseIds.length > 0 && (
        <div className="pred-cases">
          <span className="pred-cases-lbl">Benzer kararlar</span>
          <div className="pred-cases-list">
            {p.similarCaseIds.slice(0, 6).map((id, i) => (
              <span className="pred-case" key={i}>{id}</span>
            ))}
          </div>
        </div>
      )}

      {/* ZORUNLU — tahmin mahkeme garantisi değildir (CLAUDE.md kırmızı çizgi). */}
      <div className="pred-disc"><Icon.info /><span>{p.disclaimer}</span></div>
    </div>
  );
}

/* ---------- Anında "düşünüyor/yazıyor" (ChatGPT-feel hafif gösterge) ----------
   Token gelmeden önceki kısa boşluğu doldurur; ağır 4-adım stepper yerine ilk anlarda. */
export function QuickTyping({ label = "Düşünüyor" }) {
  return (
    <div className="quick-typing" role="status" aria-live="polite">
      <span className="qt-dots" aria-hidden="true">
        <span className="qt-dot"></span><span className="qt-dot"></span><span className="qt-dot"></span>
      </span>
      <span className="qt-label">{label}…</span>
    </div>
  );
}
