/* ADALET — Hukuki terim tooltip bileşeni.
   uiplaybook.dev D21 deseni → ADALET özgünü.

   Metindeki hukuki terimleri CSS-only tooltip ile vurgular:
   - <abbr data-def="..." class="legal-term"> → sıfır JS, sıfır XSS riski
   - Altın noktalı alt çizgi (--accent)
   - Hover/focus → CSS ::after tooltip (280px max, edge koruması)
   - prefers-reduced-motion saygılı (app-extra.css'de transition:none) */
import React from "react";
import { findLegalTerms } from "../lib/legalTerms.js";

/**
 * Düz metin segmentini hukuki terim işaretçileriyle zenginleştirir.
 * `renderInline` çıktısıyla (React node array) uyumlu: sadece string
 * parçalarına uygulanır.
 */
export function applyLegalTooltips(text, keyBase) {
  if (!text || typeof text !== "string") return text;
  const hits = findLegalTerms(text);
  if (!hits) return text;

  const out = [];
  let cursor = 0;
  hits.forEach(({ idx, term, def, end }, i) => {
    if (idx > cursor) out.push(text.slice(cursor, idx));
    // Gerçek metinden doğru büyük/küçük harf al, sadece tanımı sözlükten
    const original = text.slice(idx, end);
    out.push(
      <abbr
        key={keyBase + "lt" + i}
        className="legal-term"
        data-def={def}
        title={def}
        /* Edge koruması: ekranın sağına yakınsa tooltip sola yaslanır */
      >
        {original}
      </abbr>
    );
    cursor = end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}
