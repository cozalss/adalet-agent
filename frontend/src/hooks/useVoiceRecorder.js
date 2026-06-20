/* Sesli giriş kaydı (#7): mikrofondan kaydet → backend Whisper STT → transkript.
   Tarayıcı API'leri (getUserMedia + MediaRecorder) ince tutuldu; durum makinesi
   (idle→recording→transcribing) test edilebilir. Backend hazır (/multimodal/stt). */
import { useCallback, useEffect, useRef, useState } from "react";
import { sttUpload } from "../lib/api.js";

export function useVoiceRecorder({ onTranscript } = {}) {
  const [state, setState] = useState("idle"); // "idle" | "recording" | "transcribing"
  const [error, setError] = useState(null);
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  // Unmount temizliği: kayıt sürerken bileşen kalkarsa (rota değişimi, modal kapanışı)
  // mikrofon track'leri kapanmaz → sekme başlığında mikrofon ikonu kalır + kaynak sızar.
  useEffect(() => {
    return () => {
      try {
        if (recRef.current && recRef.current.state === "recording") recRef.current.stop();
      } catch {
        /* MediaRecorder zaten durmuş olabilir — yut */
      }
      streamRef.current?.getTracks?.().forEach((t) => t.stop());
    };
  }, []);

  const supported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    typeof window !== "undefined" &&
    typeof window.MediaRecorder === "function";

  const start = useCallback(async () => {
    if (!supported) {
      setError("Tarayıcınız ses kaydını desteklemiyor.");
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      const rec = new MediaRecorder(stream);
      recRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        // Mikrofon parazitini bırak (gizlilik + kaynak): track'leri durdur.
        streamRef.current?.getTracks?.().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (!blob.size) { setState("idle"); return; }
        try {
          setState("transcribing");
          const res = await sttUpload(blob);
          const text = (res?.text || "").trim();
          if (text) onTranscript?.(text);
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
      // İzin reddi / cihaz yok → kullanıcıya nazik mesaj, akışı bozma.
      setError("Mikrofon erişimi gerekli (tarayıcı izni verin).");
      setState("idle");
    }
  }, [supported, onTranscript]);

  const stop = useCallback(() => {
    if (recRef.current && state === "recording") recRef.current.stop();
  }, [state]);

  const toggle = useCallback(() => {
    if (state === "recording") stop();
    else if (state === "idle") start();
  }, [state, start, stop]);

  return { state, error, supported, start, stop, toggle };
}
