/* ADALET /sor — gerçek backend sohbet durumu (SSE faz makinesi).

   Mock SCENARIOS yerine /ask/stream'i tüketir. Her turn fazlardan geçer:
   triage → sources → drafting → final | reject | clarify
   UI (TurnView) bu faz + data şeklini olduğu gibi render eder.

   Race koruması: her akış event'i KENDİ turn'üne (key ile) yazılır — "son
   turn"e değil. Böylece kullanıcı hızlı ikinci soru sorduğunda eski akışın
   geç gelen event'i yeni turn'ü bozamaz. */
import { useCallback, useRef, useState } from "react";
import { askStream, clearSession } from "../lib/api.js";
import { mapResponse, mapClarify } from "../lib/parseAnswer.js";

const TERMINAL = ["final", "reject", "clarify"];

export function useChat() {
  const [turns, setTurns] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const convRef = useRef(null);
  const abortRef = useRef(null);
  const keyRef = useRef(0);

  const last = turns[turns.length - 1];
  const busy = !!last && !TERMINAL.includes(last.phase);

  /** Belirli turn'e (key) patch — "son turn"e değil (race koruması). */
  const _patch = useCallback((key, patch) => {
    setTurns((ts) => ts.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  }, []);

  const _patchData = useCallback((key, patch) => {
    setTurns((ts) => ts.map((x) =>
      x.key === key ? { ...x, data: { ...x.data, ...patch } } : x));
  }, []);

  /** Bir soruyu backend'e gönder, akışı turn'e bağla. */
  const ask = useCallback(async (text, opts = {}) => {
    if (!text.trim()) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const key = ++keyRef.current;

    setTurns((ts) => [...ts, {
      key,
      question: text,
      phase: "triage",
      data: { kind: "answer", domain: "", domainConfidence: null, sources: [], sourceCount: 0 },
    }]);

    const payload = {
      question: text,
      conversation_id: convRef.current || undefined,
      want_dilekce: opts.wantDilekce || false,
      image_attachments: opts.attachments || undefined,
    };

    let sawClarify = false;
    try {
      await askStream(payload, {
        onTriage: (d) => _patchData(key, {
          domain: _domainLabel(d.domain),
          domainConfidence: typeof d.confidence === "number" ? d.confidence : null,
        }),
        // Ara 'clarify' event'i yalnız SOFT-sinyal — terminal kararı onFinal'da
        // verilir. (Aksi halde phase erken 'clarify'=TERMINAL olur, busy düşer,
        // geç gelen final yanlış turn'e yazılır — race.)
        onClarify: () => { sawClarify = true; },
        onSources: (d) => {
          _patch(key, { phase: "sources" });
          _patchData(key, { sourceCount: d.count || 0 });
        },
        onDrafting: () => { if (!sawClarify) _patch(key, { phase: "drafting" }); },
        onFinal: (resp) => {
          if (resp.conversation_id) {
            convRef.current = resp.conversation_id;
            setConversationId(resp.conversation_id);
          }
          if (sawClarify || ((resp.errors || []).length === 0 && _looksClarify(resp))) {
            _patch(key, {
              phase: "clarify",
              data: { kind: "clarify", domain: _domainLabel(resp.domain), clarify: mapClarify(resp.answer) },
            });
            return;
          }
          const mapped = mapResponse(resp, text);
          _patch(key, {
            phase: mapped.kind === "reject" ? "reject" : "final",
            data: { ...mapped, sourceCount: (mapped.sources || []).length },
          });
        },
        onError: (d) => {
          _patch(key, { phase: "reject", data: {
            kind: "reject", domain: "",
            reject: { title: "Bir sorun oluştu", body: d?.detail || "Yanıt alınamadı. Lütfen tekrar deneyin." },
            lookedAt: [],
          } });
        },
      }, ac.signal);
    } catch (err) {
      if (ac.signal.aborted) return;
      _patch(key, { phase: "reject", data: {
        kind: "reject", domain: "",
        reject: {
          title: "Bağlanılamadı",
          body: "Sunucuya ulaşılamadı. Backend çalışıyor mu? (FastAPI :8000) " +
                "Geliştirme için: backend dizininde `uv run uvicorn main:app --reload`.",
        },
        lookedAt: [],
      } });
    }
  }, [_patch, _patchData]);

  /** Akışı durdur — kullanıcı uzun cevabı kesebilir. */
  const stop = useCallback(() => {
    abortRef.current?.abort();
    setTurns((ts) => ts.map((x, k) => {
      if (k !== ts.length - 1 || TERMINAL.includes(x.phase)) return x;
      return { ...x, phase: "reject", data: {
        kind: "reject", domain: x.data.domain || "",
        reject: { title: "Durduruldu", body: "Yanıt üretimi durduruldu. İsterseniz tekrar sorabilirsiniz." },
        lookedAt: [],
      } };
    }));
  }, []);

  /** Netleştirme seçeneği seçildi → cevabı yeni soru gibi gönder (bağlam korunur). */
  const pickClarify = useCallback((opt) => { ask(opt); }, [ask]);

  /** Son turn'ü sil + soruyu geri ver (retry için). */
  const retryLast = useCallback(() => {
    let q = "";
    setTurns((ts) => { q = ts[ts.length - 1]?.question || ""; return ts.slice(0, -1); });
    return q;
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    // KVKK: yeni sohbet → sunucu tarafı geçmişi + dilekçe PDF'i sil (fire-and-forget).
    clearSession(convRef.current);
    convRef.current = null;
    setConversationId(null);
    setTurns([]);
  }, []);

  return { turns, ask, stop, pickClarify, retryLast, reset, busy, conversationId };
}

function _looksClarify(resp) {
  // Heuristik: verdict pass ama cevap birden çok numaralı SORU içeriyorsa netleştirme.
  const a = resp.answer || "";
  const qLines = (a.match(/^\s*\d+[.)]\s+.+\?/gm) || []).length;
  return qLines >= 2 && (resp.citations || []).length === 0;
}

function _domainLabel(d) {
  const map = { tuketici: "Tüketici Hukuku", isHukuku: "İş Hukuku", kira: "Kira Hukuku",
    icra: "İcra Hukuku", trafik: "Trafik Hukuku", vergi: "Vergi Hukuku",
    tapu: "Tapu / Gayrimenkul", idari: "İdari Hukuk", unknown: "Belirsiz" };
  return map[d] || d || "";
}
