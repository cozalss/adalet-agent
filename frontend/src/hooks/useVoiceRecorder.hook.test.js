/* useVoiceRecorder (#7) — sesli giriş durum makinesi. Tarayıcı API'leri (getUserMedia/
   MediaRecorder) jsdom'da yok → fake'lenir; sttUpload mock'lanır. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useVoiceRecorder } from "./useVoiceRecorder.js";
import * as api from "../lib/api.js";

function setMediaDevices(value) {
  Object.defineProperty(navigator, "mediaDevices", { value, configurable: true, writable: true });
}

function installFakeMedia() {
  const tracks = [{ stop: vi.fn() }];
  const stream = { getTracks: () => tracks };
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  setMediaDevices({ getUserMedia });
  class FakeMediaRecorder {
    constructor(s) { this.stream = s; this.mimeType = "audio/webm"; this.state = "inactive"; }
    start() { this.state = "recording"; }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["aud"], { type: "audio/webm" }) });
      this.onstop?.();
    }
  }
  window.MediaRecorder = FakeMediaRecorder;
  return { getUserMedia, tracks };
}

function installFakeSpeech() {
  const instances = [];
  class FakeSpeechRecognition {
    constructor() { this.lang = ""; this.continuous = false; this.interimResults = false; instances.push(this); }
    start() { this.started = true; }
    stop() { this.onend?.(); }
    // segments: [{ final: bool, text: str }] → SpeechRecognition result event'i taklit eder
    emit(segments, resultIndex = 0) {
      const results = segments.map((s) => ({ isFinal: s.final, 0: { transcript: s.text } }));
      this.onresult?.({ resultIndex, results });
    }
  }
  window.SpeechRecognition = FakeSpeechRecognition;
  return instances;
}

afterEach(() => {
  vi.restoreAllMocks();
  setMediaDevices(undefined);
  delete window.MediaRecorder;
  delete window.SpeechRecognition;
});

describe("useVoiceRecorder", () => {
  it("desteklenmeyen tarayıcıda start → hata, kayıt başlamaz", async () => {
    setMediaDevices({ getUserMedia: vi.fn() });
    delete window.MediaRecorder; // MediaRecorder yok → supported=false
    const { result } = renderHook(() => useVoiceRecorder({}));
    expect(result.current.supported).toBe(false);
    await act(async () => { await result.current.start(); });
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toMatch(/desteklemiyor/i);
  });

  it("kayıt→durdur akışı STT'i çağırır + transkripti onTranscript'e verir + mic'i kapatır", async () => {
    const { getUserMedia, tracks } = installFakeMedia();
    const sttSpy = vi.spyOn(api, "sttUpload").mockResolvedValue({ text: "kıdem tazminatı nedir" });
    const onTranscript = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onTranscript }));

    expect(result.current.supported).toBe(true);
    await act(async () => { await result.current.start(); });
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(result.current.state).toBe("recording");

    await act(async () => { result.current.stop(); await Promise.resolve(); });
    await waitFor(() => expect(sttSpy).toHaveBeenCalled());
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("kıdem tazminatı nedir"));
    await waitFor(() => expect(result.current.state).toBe("idle"));
    expect(tracks[0].stop).toHaveBeenCalled(); // mikrofon serbest bırakıldı (gizlilik)
  });

  it("STT hatasında nazik mesaj + idle (akış bozulmaz)", async () => {
    installFakeMedia();
    vi.spyOn(api, "sttUpload").mockRejectedValue(new Error("422"));
    const { result } = renderHook(() => useVoiceRecorder({ onTranscript: vi.fn() }));
    await act(async () => { await result.current.start(); });
    await act(async () => { result.current.stop(); await Promise.resolve(); });
    await waitFor(() => expect(result.current.error).toMatch(/çevrilemedi/i));
    expect(result.current.state).toBe("idle");
  });

  it("canlı: Web Speech interim sonuçları onTranscript'e ANLIK yazar (tr-TR)", async () => {
    const instances = installFakeSpeech();
    const onTranscript = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onTranscript }));

    expect(result.current.supported).toBe(true);
    await act(async () => { result.current.start(); });
    expect(result.current.state).toBe("recording");

    const recog = instances[0];
    expect(recog.lang).toBe("tr-TR");
    expect(recog.interimResults).toBe(true);
    expect(recog.continuous).toBe(true);

    // interim (henüz final değil) → CANLI yazılır
    act(() => { recog.emit([{ final: false, text: "kıdem tazmin" }]); });
    expect(onTranscript).toHaveBeenLastCalledWith("kıdem tazmin");

    // segment finalize + yeni interim → birikmiş final + interim
    act(() => { recog.emit([{ final: true, text: "kıdem tazminatı " }, { final: false, text: "nedir" }]); });
    expect(onTranscript).toHaveBeenLastCalledWith("kıdem tazminatı nedir");

    // durdur → onend → idle
    await act(async () => { result.current.stop(); });
    expect(result.current.state).toBe("idle");
  });

  it("canlı yol media'ya tercih edilir (ikisi de varsa SpeechRecognition kullanılır)", async () => {
    const instances = installFakeSpeech();
    const { getUserMedia } = installFakeMedia();
    const { result } = renderHook(() => useVoiceRecorder({ onTranscript: vi.fn() }));
    await act(async () => { result.current.start(); });
    expect(instances).toHaveLength(1);          // Web Speech başlatıldı
    expect(getUserMedia).not.toHaveBeenCalled(); // MediaRecorder fallback'e düşülmedi
  });
});
