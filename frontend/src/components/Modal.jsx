/* ADALET paylaşımlı modal kabuğu — backdrop + odak tuzağı + Esc.
   account.css'teki .acc-modal* stillerini yeniden kullanır (DRY). */
import React, { useRef, useEffect, useId } from "react";
import { Icon } from "./icons.jsx";

export function Modal({ title, children, onClose, wide, returnFocus }) {
  const ref = useRef(null);
  const titleId = useId();
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const SEL = 'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])';
    const focusables = () => Array.from(el.querySelectorAll(SEL)).filter((n) => !n.disabled && n.offsetParent !== null);
    focusables()[0]?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab") return;
      const f = focusables(); if (!f.length) return;
      const first = f[0], lastEl = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); returnFocus?.current?.focus?.(); };
  }, [onClose, returnFocus]);

  return (
    <div className="acc-modal-backdrop" onClick={onClose}>
      <div
        className={"acc-modal" + (wide ? " wide" : "")} ref={ref} role="dialog" aria-modal="true"
        aria-labelledby={titleId} onClick={(e) => e.stopPropagation()}
      >
        <div className="acc-modal-head">
          <h3 id={titleId}>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Kapat"><Icon.close /></button>
        </div>
        <div className="acc-modal-scroll">{children}</div>
      </div>
    </div>
  );
}
