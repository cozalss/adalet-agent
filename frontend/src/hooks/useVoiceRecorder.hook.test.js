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

afterEach(() => {
  vi.restoreAllMocks();
  setMediaDevices(undefined);
  delete window.MediaRecorder;
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
});
