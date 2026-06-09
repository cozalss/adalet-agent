/* lib/api.js — backend client: SSE akış parse/dispatch + abort/hata yolları + indirme/OCR/
   temizlik/health. İnceleme 2026-06-04: api.js tümüyle test dışıydı; özellikle SSE hata/abort
   akışları kritik (kullanıcı sonsuz spinner'da kalmasın). fetch mock'lanır (saf mantık). */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  askStream,
  backendHealthy,
  clearSession,
  downloadDilekce,
  ocrUpload,
  postFeedback,
  sttUpload,
  synthesizeTTS,
} from "./api.js";

/** SSE Response sahtesi: her frame `event:`/`data:` satırları, ayraç çift-newline. */
function sseResponse(frames) {
  const text = frames.map((f) => `${f}\n\n`).join("");
  const chunks = [new TextEncoder().encode(text)];
  let i = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          read: async () =>
            i < chunks.length
              ? { value: chunks[i++], done: false }
              : { value: undefined, done: true },
        };
      },
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.fetch;
});

describe("askStream (SSE)", () => {
  it("event'leri parse edip ilgili handler'lara dağıtır", async () => {
    const frames = [
      'event: triage\ndata: {"domain":"kira","intent":"legal_answer"}',
      'event: draft_token\ndata: {"token":"merhaba"}',
      'event: final\ndata: {"kind":"answer","domain":"kira"}',
    ];
    global.fetch = vi.fn().mockResolvedValue(sseResponse(frames));
    const onTriage = vi.fn();
    const onDraftToken = vi.fn();
    const onFinal = vi.fn();

    await askStream({ question: "depozito" }, { onTriage, onDraftToken, onFinal });

    expect(onTriage).toHaveBeenCalledWith({ domain: "kira", intent: "legal_answer" });
    expect(onDraftToken).toHaveBeenCalledWith({ token: "merhaba" });
    expect(onFinal).toHaveBeenCalledWith({ kind: "answer", domain: "kira" });
  });

  it("HTTP hata → fırlatır (handler'lar çağrılmaz)", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null });
    await expect(askStream({ question: "x" }, {})).rejects.toThrow(/HTTP 500/);
  });

  it("abort sinyali fetch reddini yukarı yayar", async () => {
    global.fetch = vi.fn().mockRejectedValue(
      Object.assign(new Error("aborted"), { name: "AbortError" }),
    );
    await expect(askStream({ question: "x" }, {}, AbortSignal.abort())).rejects.toThrow();
  });

  it("bozuk 'final' frame → onError çağrılır (sonsuz spinner önlenir)", async () => {
    global.fetch = vi.fn().mockResolvedValue(sseResponse(["event: final\ndata: {bozuk"]));
    const onError = vi.fn();
    await askStream({ question: "x" }, { onError });
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toHaveProperty("detail");
  });

  it("bilinmeyen event sessizce yok sayılır (çökmeden tamamlanır)", async () => {
    global.fetch = vi.fn().mockResolvedValue(sseResponse(['event: garip\ndata: {"a":1}']));
    await expect(askStream({ question: "x" }, {})).resolves.toBeUndefined();
  });
});

describe("downloadDilekce / ocrUpload hata yolları", () => {
  it("downloadDilekce !ok → fırlatır", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    await expect(downloadDilekce("abc12345")).rejects.toThrow(/indirilemedi/);
  });

  it("ocrUpload başarılı → JSON döner; !ok → fırlatır", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "abc", n_chars: 3 }) });
    const ok = await ocrUpload(new File(["x"], "a.png", { type: "image/png" }));
    expect(ok.text).toBe("abc");

    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 415 });
    await expect(ocrUpload(new File(["x"], "a.png"))).rejects.toThrow(/OCR/);
  });
});

describe("clearSession (fire-and-forget)", () => {
  it("geçersiz/kısa id → fetch çağırmaz (backend pattern guard)", async () => {
    global.fetch = vi.fn();
    await clearSession("short");      // < 8
    await clearSession("");
    await clearSession("bad/id!chars");  // geçersiz karakter
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("geçerli id → DELETE çağırır ve ağ hatasını yutar (kullanıcıyı durdurmaz)", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("net down"));
    await expect(clearSession("validid12345")).resolves.toBeUndefined();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("postFeedback (denetim #24)", () => {
  it("conversationId yoksa ağ çağrısı YAPMAZ (skip)", async () => {
    global.fetch = vi.fn();
    const r = await postFeedback({ conversationId: "", rating: "up" });
    expect(global.fetch).not.toHaveBeenCalled();
    expect(r.skipped).toBe(true);
  });

  it("conversationId varsa /feedback'e doğru gövdeyle POST eder", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, feedback_id: "fb_1" }),
    });
    const r = await postFeedback({ conversationId: "c1", rating: "down", comment: "eksik", turnIndex: 2 });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("/feedback");
    expect(opts.method).toBe("POST");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(opts.body);
    expect(body).toMatchObject({ conversation_id: "c1", rating: "down", comment: "eksik", turn_index: 2 });
    expect(r.feedback_id).toBe("fb_1");
  });

  it("backend hatası → throw (çağıran .catch ile yutar, UX bozulmaz)", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    await expect(postFeedback({ conversationId: "c1", rating: "up" })).rejects.toThrow();
  });
});

describe("sttUpload / synthesizeTTS (sesli mod #7)", () => {
  it("sttUpload: /multimodal/stt'e audio multipart POST eder, {text} döner", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ text: "kıdem tazminatı nedir", language: "tr" }),
    });
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: "audio/webm" });
    const r = await sttUpload(blob);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("/multimodal/stt");
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
    expect(opts.body.get("audio")).toBeTruthy();
    expect(r.text).toBe("kıdem tazminatı nedir");
  });

  it("sttUpload: backend hatası → throw", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 422 });
    await expect(sttUpload(new Blob(["x"]))).rejects.toThrow();
  });

  it("synthesizeTTS: /multimodal/tts'e JSON POST eder, audio Blob döner", async () => {
    const wav = new Blob([new Uint8Array([0x52, 0x49, 0x46, 0x46])], { type: "audio/wav" });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, blob: async () => wav });
    const out = await synthesizeTTS("Merhaba", { stripDisclaimer: true });
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("/multimodal/tts");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(opts.body);
    expect(body).toMatchObject({ text: "Merhaba", strip_disclaimer: true });
    expect(out).toBeInstanceOf(Blob);
  });

  it("synthesizeTTS: backend hatası → throw", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    await expect(synthesizeTTS("x")).rejects.toThrow();
  });
});

describe("backendHealthy", () => {
  it("ok → true", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true });
    expect(await backendHealthy()).toBe(true);
  });

  it("fetch reddi (timeout/ağ) → false (mock fallback kararı için)", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("timeout"));
    expect(await backendHealthy()).toBe(false);
  });
});
