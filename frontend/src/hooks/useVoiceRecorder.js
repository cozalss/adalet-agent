/* Sesli giriş (#7): konuşmayı metne çevir.
   ÖNCELİK — canlı: tarayıcı Web Speech API (SpeechRecognition) ile konuşulanı ANLIK
   (interim sonuçlar) input'a yazar (Chrome/Edge; lang=tr-TR).
   FALLBACK — Web Speech yoksa (Firefox/bazı Safari): MediaRecorder ile kaydet → backend
   /multimodal/stt (OpenAI gpt-4o-transcribe / lokal Whisper) ile toplu çevir.
   Durum makinesi (idle→recording→transcribing) korunur; transcribing yalnız fallback'te. */
import { useCallback, useEffect, useRef, useState } from "react";
import { sttUpload } from "../lib/api.js";

// Call-time okunur (modül-const DEĞİL) → test enjekte edebilir + geç tanımlanan API yakalanır.
function getSpeechRecognition() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function useVoiceRecorder({ onTranscript } = {}) {
  const [state, setState] = useState("idle"); // "idle" | "recording" | "transcribing"
  const [error, setError] = useState(null);

  // onTranscript'i ref'te tut → recognition event handler'ında stale closure olmasın.
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  // Web Speech (canlı) — kesinleşmiş metni interim'in altına biriktir.
  const recogRef = useRef(null);
  const finalRef = useRef("");

  // MediaRecorder fallback refs
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  const liveSupported = !!getSpeechRecognition();
  const mediaSupported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    typeof window !== "undefined" &&
    typeof window.MediaRecorder === "function";
  const supported = liveSupported || mediaSupported;

  /* ---------- Web Speech: canlı transkripsiyon ---------- */
  const startLive = useCallback(() => {
    setError(null);
    const SR = getSpeechRecognition();
    let recog;
    try {
      recog = new SR();
    } catch {
      setError("Sesli giriş başlatılamadı.");
      return;
    }
    recog.lang = "tr-TR";
    recog.continuous = true;       // duraklamada hemen kapanma → uzun soru yazılabilir
    recog.interimResults = true;   // ANLIK ara-sonuçlar (canlı yazım)
    finalRef.current = "";
    recog.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const seg = e.results[i];
        if (seg.isFinal) finalRef.current += seg[0].transcript;
        else interim += seg[0].transcript;
      }
      const text = (finalRef.current + interim).replace(/\s+/g, " ").trim();
      if (text) onTranscriptRef.current?.(text); // input'u CANLI güncelle
    };
    recog.onerror = (e) => {
      // no-speech / aborted (kullanıcı durdurdu) sessiz; gerçek hatayı göster.
      if (e?.error && e.error !== "aborted" && e.error !== "no-speech") {
        setError(
          e.error === "not-allowed"
            ? "Mikrofon erişimi gerekli (tarayıcı izni verin)."
            : "Ses algılanamadı, tekrar deneyin.",
        );
      }
    };
    recog.onend = () => {
      recogRef.current = null;
      setState("idle");
    };
    recogRef.current = recog;
    try {
      recog.start();
      setState("recording");
    } catch {
      recogRef.current = null;
      setState("idle");
      setError("Sesli giriş başlatılamadı, tekrar deneyin.");
    }
  }, []);

  /* ---------- MediaRecorder → backend STT (fallback) ---------- */
  const startMedia = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      const rec = new MediaRecorder(stream);
      recRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        streamRef.current?.getTracks?.().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (!blob.size) { setState("idle"); return; }
        try {
          setState("transcribing");
          const res = await sttUpload(blob);
          const text = (res?.text || "").trim();
          if (text) onTranscriptRef.current?.(text);
          else setError("Konuşma algılanamadı, tekrar deneyin.");
        } catch {
          setError("Ses metne çevrilemedi, tekrar deneyin.");
        } finally {
          setState("idle");
        }
      };
      rec.start();
      setState("recording");
    } catch {
      setError("Mikrofon erişimi gerekli (tarayıcı izni verin).");
      setState("idle");
    }
  }, []);

  const start = useCallback(() => {
    if (liveSupported) startLive();
    else if (mediaSupported) startMedia();
    else setError("Tarayıcınız ses kaydını desteklemiyor.");
  }, [liveSupported, mediaSupported, startLive, startMedia]);

  const stop = useCallback(() => {
    if (recogRef.current) {
      try { recogRef.current.stop(); } catch { /* zaten durmuş */ }
      return;
    }
    if (recRef.current && state === "recording") recRef.current.stop();
  }, [state]);

  const toggle = useCallback(() => {
    if (state === "recording") stop();
    else if (state === "idle") start();
  }, [state, start, stop]);

  // Unmount temizliği: kayıt sürerken bileşen kalkarsa recognition/mikrofon sızmasın.
  useEffect(() => {
    return () => {
      try { recogRef.current?.stop(); } catch { /* yut */ }
      try { if (recRef.current?.state === "recording") recRef.current.stop(); } catch { /* yut */ }
      streamRef.current?.getTracks?.().forEach((t) => t.stop());
    };
  }, []);

  return { state, error, supported, start, stop, toggle };
}
