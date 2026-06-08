/* Ajan Akış Şeması — canlı LangGraph görselleştirmesi (custom SVG, sıfır ek dep).
   Kullanıcı sorusu işlenirken hangi ajanın çalıştığını, paralel kolları, doğrulama
   skorlarını gerçek-zamanlı + şık gösterir. RED-LINE: yalnız İLERLEME görselleştirir;
   doğrulama SONUCU backend'de (n_verified/confidence final event'inden gelir). */
import React from "react";
import { NODES, EDGES, deriveNodeStatus, buildFigcaption, verifyTone } from "./topology.js";

// SVG yerleşimi — col/row → piksel (yatay akış, mevzuat∥emsal dikey çatal).
const PAD_X = 58;
const COL_W = 118;
const ROW_Y = [40, 104, 168];
const NODE_W = 94;
const NODE_H = 48;
const VIEW_W = PAD_X * 2 + 5 * COL_W;
const VIEW_H = 208;

const cx = (col) => PAD_X + col * COL_W;
const cy = (row) => ROW_Y[row];
const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));

// Düğüm sağ-kenarından sonraki düğüm sol-kenarına yumuşak bezier kenar.
function edgePath(from, to) {
  const a = byId[from];
  const b = byId[to];
  const x1 = cx(a.col) + NODE_W / 2;
  const y1 = cy(a.row);
  const x2 = cx(b.col) - NODE_W / 2;
  const y2 = cy(b.row);
  const mx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
}

export function AgentFlowGraph({
  phase,
  activeNode = null,
  intent = null,
  retryCount = 0,
  sources = null,
  verify = null,
}) {
  const status = deriveNodeStatus({ phase, activeNode, intent });
  const caption = buildFigcaption(status);
  const showRetry = retryCount > 0;

  // Bir kenar, hedef düğümü aktif/done ise "akar" (gold çizgi).
  const edgeState = (e) => {
    const t = status[e.to];
    if (t === "active") return "flowing";
    if (t === "done") return "done";
    return "idle";
  };

  return (
    <figure className="agw-figure" role="figure" aria-label="Ajan akış şeması">
      <div className="agw-head">
        <span className="agw-title">Ajan Ekibi</span>
        {sources && (sources.mevzuat || sources.emsal) ? (
          <span className="agw-chip" aria-hidden="true">
            📑 {sources.mevzuat ?? 0} kanun · {sources.emsal ?? 0} içtihat taranıyor
          </span>
        ) : null}
        {showRetry ? (
          <span className="agw-chip agw-chip-retry" aria-hidden="true">↻ yeniden üretiliyor ({retryCount})</span>
        ) : null}
      </div>

      <svg className="agw-svg" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="presentation" aria-hidden="true">
        {/* Kenarlar (düğümlerin ALTINDA) */}
        <g className="agw-edges">
          {EDGES.map((e) => (
            <path
              key={`${e.from}-${e.to}`}
              className={`agw-edge agw-edge-${edgeState(e)}`}
              d={edgePath(e.from, e.to)}
              fill="none"
            />
          ))}
          {showRetry ? (
            <path
              className="agw-edge agw-edge-retry"
              d={`M ${cx(byId.debate.col)} ${cy(byId.debate.row) + NODE_H / 2} C ${cx(2)} 196, ${cx(2)} 196, ${cx(byId.draft.col)} ${cy(byId.draft.row) + NODE_H / 2}`}
              fill="none"
            />
          ) : null}
        </g>

        {/* Düğümler */}
        <g className="agw-nodes">
          {NODES.map((n) => {
            const st = status[n.id];
            const x = cx(n.col) - NODE_W / 2;
            const y = cy(n.row) - NODE_H / 2;
            return (
              <g key={n.id} className={`agw-node agw-node-${st}`} transform={`translate(${x} ${y})`}>
                {st === "active" ? (
                  <rect className="agw-pulse" x="-4" y="-4" width={NODE_W + 8} height={NODE_H + 8} rx="14" />
                ) : null}
                <rect className="agw-card" width={NODE_W} height={NODE_H} rx="11" />
                <text className="agw-dot" x={NODE_W - 13} y="16" aria-hidden="true">
                  {st === "done" ? "✓" : st === "active" ? "●" : ""}
                </text>
                <text className="agw-label" x="11" y="20">{n.label}</text>
                <text className="agw-sub" x="11" y="35">{n.sub}</text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Doğrulama rozeti — yalnız final geldiğinde (backend kararı; renk DEĞİL metin-kodlu) */}
      {verify && verify.nTotal != null ? (
        <div
          className={`agw-verify agw-verify-${verifyTone(verify.confidenceLabel)}`}
          aria-label={`Doğrulama: ${verify.nVerified}/${verify.nTotal} iddia kaynakla doğrulandı.${verify.confidenceLabel ? " Güven: " + verify.confidenceLabel + "." : ""}`}
        >
          <span className="agw-verify-num">{verify.nVerified}/{verify.nTotal}</span>
          <span className="agw-verify-txt">iddia doğrulandı</span>
          {verify.confidenceLabel ? <span className="agw-verify-conf">· Güven: {verify.confidenceLabel}</span> : null}
        </div>
      ) : null}

      {/* a11y: figure aria-label statik ad sağlar; TEK aria-live bölge dinamik durumu
          duyurur (figcaption + live çift-okumasını önlemek için yalnız status region). */}
      <figcaption className="agw-sr" role="status" aria-live="polite">{caption}</figcaption>
    </figure>
  );
}
