/* ADALET /sor — cevap, reddetme, netleştirme, kullanıcı balonu.
   Prototipten birebir; Icon ES import. */
import React, { useState, useRef, useEffect } from "react";
import { Icon } from "./icons.jsx";
import { RunText, renderInline } from "./ui.jsx";
import { stripAnswerTail, cleanDraftText } from "../lib/parseAnswer.js";
import { BorderBeam } from "./ui/border-beam.jsx";

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
    <div className="card answer" ref={cardRef} style={{ position: "relative", overflow: "hidden" }}>
      {/* magicui — kenarda dolaşan ince terracotta→gold ışık (AI-üretildi + doğrulandı sinyali) */}
      <BorderBeam size={70} duration={9} colorFrom="#9e6a43" colorTo="#e2bd91" className="opacity-60" />
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
  // `options` = SORULAR → tıklanamaz okunabilir liste (eski hata: soruya tıklayınca soru-metni
  // mesaj olarak gidiyordu). `chips` = backend'in CEVAP-şıkları (ör. tahliye sebepleri) →
  // tıklanabilir: tıklayınca o sebep kullanıcı YANITI olarak gider, sebebe-özel round-2'yi
  // tetikler. Soru-tıklama hatası tekrarlanmaz çünkü chip'ler cevaptır, soru değil.
  // Savunmacı: data mapClarify dışı (ör. geçmiş-replay / bozuk yanıt) gelse de render
  // çökmesin — options/chips her zaman dizi olarak ele alınır.
  const options = Array.isArray(data.options) ? data.options : [];
  const chips = Array.isArray(data.chips) ? data.chips : [];
  return (
    <div className="card clarify soft" aria-live="polite">
      <p className="cl-q">{data.intro}</p>
      <ul className="cl-opts" aria-label="Netleştirme soruları">
        {options.map((o, i) => (
          <li className="cl-opt" key={i}>
            <span className="cl-arrow" aria-hidden="true">→</span>{o}
          </li>
        ))}
      </ul>
      {chips.length > 0 && (
        <div className="cl-chips" role="group" aria-label="Hızlı seçenekler">
          {chips.map((c, i) => (
            <button type="button" className="cl-chip" key={i} onClick={() => onPick?.(c)}>
              {c}
            </button>
          ))}
        </div>
      )}
      <p className="cl-hint">
        {chips.length > 0
          ? "Yukarıdan bir seçeneğe tıklayabilir ya da yanıtınızı aşağıya yazabilirsiniz."
          : "Yanıtınızı aşağıya yazabilirsiniz — birkaçını birden yanıtlamanız yeterli."}
      </p>
    </div>
  );
}

/** Hafif sohbet baloncuğu — KART DEĞİL (gölge/border yok). Selam/yönlendirme yanıtı;
 *  ChatGPT-benzeri sol-hizalı düz metin. Hukuki iddia/kaynak yok → güvenli. */
export function SmallTalkBubble({ text }) {
  // Finalize kuyruğunu (⚠️ disclaimer + Kaynaklar) kes — hem CANLI streaming (ham draftText)
  // hem final aynı temiz gövdeyi gösterir → "akışta var, final'de yok" flip'i biter.
  const paras = stripAnswerTail(text).split(/\n{2,}/).filter((p) => p.trim());
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

/** Hukuki yol CANLI taslak baloncuğu — token'lar geldikçe yazılır (ChatGPT hissi).
 *  Açıkça GEÇİCİ: "yazılıyor · doğrulanacak" rozeti + yanıp sönen imleç. Final
 *  gelince TurnView bunu doğrulanmış AnswerCard ile DEĞİŞTİRİR (ham taslak düşer).
 *  Böylece kullanıcı beklemez (anlık yazım görür) ama metnin nihai olmadığını bilir. */
export function DraftStreamBubble({ text }) {
  // cleanDraftText: finalize kuyruğu + ham [src:..] etiketleri + yarım-stream guard.
  // renderInline: **kalın** markdown → <strong> (final kartla tutarlı; literal yıldız YOK).
  const clean = cleanDraftText(text || "");
  const paras = clean.split(/\n{2,}/).filter((p) => p.trim());
  return (
    <div className="draft-stream" aria-live="polite">
      <div className="draft-stream-head">
        <span className="draft-pulse" aria-hidden="true"></span>
        <span className="draft-tag">Yazılıyor — birazdan kaynaklarla doğrulanacak</span>
      </div>
      <div className="draft-stream-body">
        {paras.map((para, i) => (
          <p key={i}>
            {para.split("\n").map((line, j) => (
              <React.Fragment key={j}>{j > 0 && <br />}{renderInline(line, `d${i}_${j}`)}</React.Fragment>
            ))}
            {i === paras.length - 1 && <span className="draft-caret" aria-hidden="true"></span>}
          </p>
        ))}
      </div>
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
