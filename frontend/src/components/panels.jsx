/* ADALET /sor — repo-ilhamı paneller (özgün uyarlama).

   - AgentTrace:  vercel/ai-chatbot reasoning.tsx + morphic collapsible-message
                  → ADALET'in 7-ajan + Doğrulama farkını gösteren açılır şeffaflık
                  paneli (claims + debate notes). Kimsede yok; jüri/yarışma "wow".
   - PredictionCard: 8. ajan (Tahmin) — geçmiş Yargıtay'a dayalı istatistiksel
                  tahmin. Disclaimer ZORUNLU (mahkeme garantisi değil).
   - ThinkingSkeleton: vercel shimmer — draft hazırlanırken cevabın yerini tutar. */
import React, { useState } from "react";
import { Icon } from "./icons.jsx";

/* ---------- Ajan-izi / doğrulama şeffaflık paneli (açılır) ---------- */
export function AgentTrace({ claims, debateNotes, retryCount, sourceCount }) {
  const [open, setOpen] = useState(false);
  const list = claims || [];
  const total = list.length;
  const okCount = list.filter((c) => c.verified).length;

  // Gösterilecek bir şey yoksa render etme (DRY/temizlik).
  if (!total && !debateNotes) return null;

  const summary = total > 0
    ? `${okCount}/${total} iddia kaynakla doğrulandı`
    : `${sourceCount || 0} kaynak incelendi`;

  return (
    <div className={"agent-trace" + (open ? " open" : "")}>
      <button
        className="at-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
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
        <div className="at-body">
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

/* ---------- Düşünme/draft iskeleti (shimmer) ---------- */
export function ThinkingSkeleton() {
  return (
    <div className="card answer thinking-skl" aria-hidden="true">
      <div className="skl" style={{ height: 12, width: "38%", marginBottom: 13 }}></div>
      <div className="skl" style={{ height: 11, width: "100%", marginBottom: 8 }}></div>
      <div className="skl" style={{ height: 11, width: "93%", marginBottom: 8 }}></div>
      <div className="skl" style={{ height: 11, width: "58%" }}></div>
    </div>
  );
}
