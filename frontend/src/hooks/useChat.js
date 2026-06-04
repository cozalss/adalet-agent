/* ADALET /sor — gerçek backend sohbet durumu (SSE faz makinesi).

   Mock SCENARIOS yerine /ask/stream'i tüketir. Her turn fazlardan geçer:
   triage → sources → drafting → final | reject | clarify
   UI (TurnView) bu faz + data şeklini olduğu gibi render eder.

   Race koruması: her akış event'i KENDİ turn'üne (key ile) yazılır — "son
   turn"e değil. Böylece kullanıcı hızlı ikinci soru sorduğunda eski akışın
   geç gelen event'i yeni turn'ü bozamaz. */
import { useCallback, useRef, useState } from "react";
import { askStream } from "../lib/api.js";
import { mapResponse, mapClarify, looksSmalltalk, mapSmalltalk } from "../lib/parseAnswer.js";

const TERMINAL = ["final", "reject", "clarify", "smalltalk"];

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
    let sawSmalltalk = false;
    try {
      await askStream(payload, {
        onTriage: (d) => {
          // Hafif yollar (selam/yönlendirme/kapsam-dışı): erken işaretle → token akmaz,
          // ağır stepper yerine hafif "yazıyor", final'da soğuk RejectCard değil baloncuk.
          // "chat" DAHİL (selam/genel sohbet de hafif baloncuk yolu) — eksikti: chat
          // intent'i ağır "drafting" yolundan akıp final'de hafif baloncuğa FLIP ediyordu.
          if (["chat", "smalltalk", "redirect", "out_of_scope_sensitive"].includes(d.intent)) {
            sawSmalltalk = true;
          }
          _patchData(key, {
            domain: _domainLabel(d.domain),
            domainConfidence: typeof d.confidence === "number" ? d.confidence : null,
            intent: d.intent || null,
          });
        },
        // Ara 'clarify' event'i yalnız SOFT-sinyal — terminal kararı onFinal'da
        // verilir. (Aksi halde phase erken 'clarify'=TERMINAL olur, busy düşer,
        // geç gelen final yanlış turn'e yazılır — race.)
        onClarify: () => { sawClarify = true; },
        onSources: (d) => {
          _patch(key, { phase: "sources" });
          _patchData(key, { sourceCount: d.count || 0 });
        },
        onNode: () => {}, // node event'i UI'da işlenmez — sessiz yutulurdu, şimdi açık no-op
        // Canlı yazım: draft token'ları üretildikçe biriktir + "drafting" fazına geç.
        // DOĞRULANMAMIŞ taslak — UI "yazıyor/doğrulanıyor" rozetiyle gösterir; final
        // gelince mapResponse data'yı doğrulanmış cevapla DEĞİŞTİRİR (draftText düşer).
        onDraftToken: (d) => {
          // clarifier LLM'siz (token yok) → orada kapat. AMA chat node (selam/genel)
          // ARTIK streaming → tokenları göster (ChatGPT-gibi canlı yazım). sawSmalltalk'ta
          // bile akıt: hukuki-olmayan chat yanıtı canlı baloncukta yazılsın.
          if (sawClarify) return;
          setTurns((ts) => ts.map((x) =>
            x.key === key
              ? { ...x, phase: "drafting",
                  data: { ...x.data, draftText: (x.data.draftText || "") + (d.t || "") } }
              : x));
        },
        onDrafting: () => { if (!sawClarify && !sawSmalltalk) _patch(key, { phase: "drafting" }); },
        onVerifying: () => { if (!sawClarify && !sawSmalltalk) _patch(key, { phase: "verifying" }); },
        onTiming: () => {}, // timing latency event — gelecekte metrikler için; şimdi no-op
        onFinal: (resp) => {
          if (ac.signal.aborted) return; // stop sonrası gecikmeli final → state'i ezme
          if (resp.conversation_id) {
            convRef.current = resp.conversation_id;
            setConversationId(resp.conversation_id);
          }
          // Smalltalk/yönlendirme → hafif baloncuk (soğuk RejectCard DEĞİL). clarify'dan
          // ÖNCE: SSE intent geldiyse final ne derse desin (reject olsa bile) baloncuk basar.
          if (sawSmalltalk || looksSmalltalk(resp)) {
            _patch(key, { phase: "smalltalk", data: mapSmalltalk(resp) });
            return;
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
          if (ac.signal.aborted) return;
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

  /** Kullanıcı mesajını düzenle & yeniden gönder: o turn'ü ve sonrasını sil,
   *  yeni metni sor (aynı conversation_id ile — düzeltme bağlamı korunur). */
  const editFrom = useCallback((turnKey, newText) => {
    if (!newText.trim()) return;
    setTurns((ts) => {
      const idx = ts.findIndex((t) => t.key === turnKey);
      return idx === -1 ? ts : ts.slice(0, idx);
    });
    ask(newText);
  }, [ask]);

  /** Son turn'ü sil + soruyu geri ver (retry için). */
  const retryLast = useCallback(() => {
    const q = turns[turns.length - 1]?.question || "";
    setTurns((ts) => ts.slice(0, -1));
    return q;
  }, [turns]);

  // "Yeni sohbet": geçmiş artık KALICI (App geçmişe kaydeder) → reset yalnız
  // görünümü temizler, sunucu DELETE'i YOK. undoReset son görünümü geri getirir
  // (yanlışlıkla yeni sohbet açılırsa). Sohbet zaten geçmişte durur.
  const clearedRef = useRef(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    const prevTurns = turns;
    clearedRef.current = prevTurns.length ? { turns: prevTurns, convId: convRef.current } : null;
    convRef.current = null;
    setConversationId(null);
    setTurns([]);
    return prevTurns.length > 0; // çağıran undo göstersin mi?
  }, [turns]);

  /** Geri-al: son temizlenen görünümü geri getir. */
  const undoReset = useCallback(() => {
    const saved = clearedRef.current;
    if (!saved) return;
    clearedRef.current = null;
    convRef.current = saved.convId;
    setConversationId(saved.convId);
    setTurns(saved.turns);
  }, []);

  /** Geçmiş bir sohbeti yükle (sidebar'dan tıklanınca) — turn'leri taze key'le geri koy. */
  const loadConversation = useCallback((conv) => {
    abortRef.current?.abort();
    convRef.current = conv.id;
    setConversationId(conv.id);
    setTurns((conv.turns || []).map((t) => ({ ...t, key: ++keyRef.current })));
  }, []);

  return {
    turns, ask, stop, pickClarify, retryLast, editFrom, reset, undoReset,
    loadConversation, busy, conversationId,
  };
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
