/* ADALET /sor — cevap, reddetme, netleştirme, kullanıcı balonu.
   Prototipten birebir; Icon ES import. */
import React, { useState, useRef, useEffect } from "react";
import { Icon } from "./icons.jsx";
import { RunText } from "./ui.jsx";

export function AnswerCard({ answer, sources, onJump }) {
  const cardRef = useRef(null);
  // Savunmacı: geçmişten yüklenen eski/kısmi kayıtlarda sections olmayabilir →
  // text'ten tek bölüme düş (uygulama beyaz ekrana düşmesin).
  const sections = (answer?.sections && answer.sections.length)
    ? answer.sections
    : [{ label: "Cevap", lead: true, runs: [{ t: answer?.text || "" }] }];

  // Cevap gelince bölümleri SIRAYLA aç ("bir anda dökülme" yerine yazılma hissi):
  // her bölüm bir öncekinden ~200ms sonra yukarıdan belirir, o an "yazılan" bölümün
  // etiketinde yanıp sönen gold imleç olur. prefers-reduced-motion: anında göster.
  useEffect(() => {
    const el = cardRef.current; if (!el) return;
    const secs = Array.from(el.querySelectorAll(".sec"));
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      secs.forEach((s) => s.classList.add("visible"));
      return;
    }
    const STAGGER = 360; // ms — bölüm başına (belirgin sıralı yazılma hissi)
    const timers = secs.map((s, i) => setTimeout(() => {
      s.classList.add("visible", "writing");
      secs[i - 1]?.classList.remove("writing"); // imleç bir sonraki bölüme geçer
    }, 80 + i * STAGGER));
    // son bölümün imlecini kısa süre sonra kaldır (yazma bitti)
    timers.push(setTimeout(
      () => secs[secs.length - 1]?.classList.remove("writing"),
      80 + secs.length * STAGGER + 600,
    ));
    return () => timers.forEach(clearTimeout);
  }, [sections.length]);

  return (
    <div className="card answer" ref={cardRef}>
      {sections.map((sec, i) => (
        <div className="sec reveal-target" key={i}>
          <div className="sec-label">{sec.label}</div>
          {sec.steps ? (
            <ol className="steps">
              {sec.steps.map((st, j) => <li key={j}>{st}</li>)}
            </ol>
          ) : (
            <p className={sec.lead ? "lead" : ""}>
              <RunText runs={sec.runs ?? []} sources={sources} onJump={onJump} />
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

export function RejectCard({ data, onRetry }) {
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

export function ClarifyCard({ data, onPick }) {
  // Yumuşak (soft): glass-ağırlık yerine sıcak zemin; numara yerine ok-ipucu → "diktat"
  // değil sohbet tonu. Selam ASLA buraya/RejectCard'a düşmez (useChat smalltalk dalı önce).
  return (
    <div className="card clarify soft" aria-live="polite">
      <p className="cl-q">{data.intro}</p>
      <div className="cl-opts">
        {data.options.map((o, i) => (
          <button className="cl-opt" key={i} onClick={() => onPick(o)}>
            <span className="cl-arrow" aria-hidden="true">→</span>{o}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Hafif sohbet baloncuğu — KART DEĞİL (gölge/border yok). Selam/yönlendirme yanıtı;
 *  ChatGPT-benzeri sol-hizalı düz metin. Hukuki iddia/kaynak yok → güvenli. */
export function SmallTalkBubble({ text }) {
  const paras = (text || "").split(/\n{2,}/).filter((p) => p.trim());
  return (
    <div className="smalltalk-bubble" aria-live="polite">
      {paras.map((para, i) => (
        <p key={i}>
          {para.split("\n").map((line, j) => (
            <React.Fragment key={j}>{j > 0 && <br />}{line}</React.Fragment>
          ))}
        </p>
      ))}
    </div>
  );
}

export function UserBubble({ text, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(text);
  const ref = useRef(null);

  useEffect(() => {
    if (!editing || !ref.current) return;
    const el = ref.current;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [editing]);

  const save = () => {
    const t = val.trim();
    if (t && t !== text) onEdit?.(t);
    setEditing(false);
  };
  const cancel = () => { setVal(text); setEditing(false); };

  if (editing) {
    return (
      <div className="msg user editing">
        <div className="bubble edit">
          <textarea
            ref={ref} value={val} rows={1}
            onChange={(e) => { setVal(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px"; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(); }
              else if (e.key === "Escape") { e.preventDefault(); cancel(); }
            }}
            aria-label="Mesajı düzenle"
          />
          <div className="edit-actions">
            <button className="btn-sm" onClick={cancel}>Vazgeç</button>
            <button className="btn-sm primary" onClick={save}>Gönder</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="msg user">
      <div className="bubble">{text}</div>
      {onEdit && (
        <button className="bubble-edit" onClick={() => { setVal(text); setEditing(true); }} aria-label="Mesajı düzenle" title="Düzenle">
          <Icon.pencil />
        </button>
      )}
    </div>
  );
}
