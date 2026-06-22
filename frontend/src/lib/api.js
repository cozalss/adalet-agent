/* ADALET backend client — SSE streaming + dilekçe + OCR.
   Vite dev proxy /ask,/api,/multimodal → FastAPI :8000. */

/** Backend isteklerine Supabase oturum JWT'sini ekle (varsa). Auth artık Supabase
 *  GoTrue ile; supabase-js erişim token'ını localStorage'da `sb-<ref>-auth-token`
 *  altında tutar. Token yoksa (oturum açılmamış) header yok → backend anonim işler.
 *  Phase C: backend bu Supabase JWT'sini SUPABASE_JWT_SECRET ile doğrular. */
function authHeaders() {
  const t = supabaseAccessToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** supabase-js'in localStorage'da sakladığı oturumdan erişim token'ını oku (senkron). */
function supabaseAccessToken() {
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i);
      if (k && k.startsWith("sb-") && k.endsWith("-auth-token")) {
        const v = JSON.parse(localStorage.getItem(k) || "null");
        if (v?.access_token) return v.access_token;
      }
    }
  } catch { /* parse/erişim hatası → token yok say */ }
  return null;
}

/**
 * POST /ask/stream — SSE akışını oku, her event için handler çağır.
 * @param {object} payload {question, conversation_id?, want_dilekce?, image_attachments?}
 * @param {object} handlers {onNode,onTriage,onClarify,onSources,onDrafting,onTiming,onFinal,onError}
 * @param {AbortSignal} [signal]
 */
export async function askStream(payload, handlers, signal) {
  const res = await fetch("/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ ...payload, stream: true }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`/ask/stream HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  // SSE inaktivite-watchdog: backend yanıt vermeyi keserse (hiç olay gelmezse) kullanıcı sonsuz
  // "yazıyor…"da kalmasın. Her olayda sıfırlanır; IDLE_MS sessizlikte reader iptal edilir + onError.
  const IDLE_MS = 45000;
  let idleAborted = false;
  let idleTimer = null;
  const armIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { idleAborted = true; reader.cancel().catch(() => {}); }, IDLE_MS);
  };

  const dispatch = (event, data) => {
    switch (event) {
      case "node": handlers.onNode?.(data); break;
      case "triage": handlers.onTriage?.(data); break;
      case "clarify": handlers.onClarify?.(data); break;
      case "sources": handlers.onSources?.(data); break;
      case "draft_token": handlers.onDraftToken?.(data); break;
      case "drafting": handlers.onDrafting?.(data); break;
      case "verifying": handlers.onVerifying?.(data); break;
      case "reasoning": handlers.onReasoning?.(data); break;
      case "timing": handlers.onTiming?.(data); break;
      case "final": handlers.onFinal?.(data); break;
      case "error": handlers.onError?.(data); break;
      default: break;
    }
  };

  armIdle();
  try {
   while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    armIdle(); // aktivite geldi → inaktivite sayacını sıfırla
    buf += decoder.decode(value, { stream: true });
    // SSE frame ayracı: çift newline
    let sep;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      const dataLines = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) {
        try { dispatch(event, JSON.parse(dataLines.join("\n"))); }
        catch (err) {
          // Yarım frame normaldir; ama 'final'/'error' parse edilemezse kullanıcı
          // sonsuz spinner'da kalır — geliştirme için görünür kıl.
          if (event === "final" || event === "error") {
            // Yalnız DEV'de konsola yaz (prod'da console yok kuralı); kullanıcıya zaten
            // onError mesajı gider. err = parse hatası (frame içeriği değil → PII yok).
            if (import.meta.env.DEV) {
              console.warn("[ADALET] SSE frame parse edilemedi:", event, err);
            }
            handlers.onError?.({ detail: "Yanıt çözümlenemedi, lütfen tekrar deneyin." });
          }
        }
      }
    }
   }
  } finally {
    if (idleTimer) clearTimeout(idleTimer);
  }
  if (idleAborted) {
    handlers.onError?.({ detail: "Sunucu yanıt vermiyor (zaman aşımı). Lütfen tekrar deneyin." });
  }
}

/** Dilekçe indirme URL'leri (auth ile fetch edilip blob indirilir). */
export async function downloadDilekce(conversationId, format = "pdf") {
  const id = encodeURIComponent(conversationId);
  const path = format === "docx" ? `/api/dilekce/${id}/docx` : `/api/dilekce/${id}`;
  const res = await fetch(path, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Dilekçe indirilemedi (HTTP ${res.status})`);
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  // Güvenlik: yol bileşenlerini at + güvenli karakterlere kısıtla (path traversal).
  const raw = m ? m[1] : `dilekce.${format}`;
  const filename = raw.split(/[/\\]/).pop().replace(/[^\w.\-À-ɏ]/g, "_") || `dilekce.${format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

/** POST /multimodal/ocr — görüntü/PDF → metin (case_facts'e beslenir). */
export async function ocrUpload(file) {
  const form = new FormData();
  form.append("image", file);
  const res = await fetch("/multimodal/ocr", {
    method: "POST", headers: authHeaders(), body: form,
  });
  if (!res.ok) {
    // Backend `detail` mesajını yüzeye çıkar (415 "Desteklenmeyen tip",
    // 413 boyut, 400 boş dosya) — kullanıcı genel hata yerine nedeni görsün.
    let detail = null;
    try { detail = (await res.json())?.detail; } catch { /* gövdesiz hata yanıtı */ }
    throw new Error(detail || `OCR başarısız (HTTP ${res.status})`);
  }
  return res.json(); // {text, engine, n_chars, error, page_count, ...}
}

/** POST /multimodal/stt — ses dosyası/blob → Türkçe metin (sesli giriş, #7).
 *  Whisper backend; döner {text, language, duration_s, ...}. */
export async function sttUpload(audio) {
  const form = new FormData();
  form.append("audio", audio);
  const res = await fetch("/multimodal/stt", {
    method: "POST", headers: authHeaders(), body: form,
  });
  if (!res.ok) throw new Error(`STT başarısız (HTTP ${res.status})`);
  return res.json();
}

/** POST /multimodal/tts — metin → audio/wav Blob (sesli okuma, #7). Piper backend.
 *  Disclaimer varsayılan kesilir (TTS okunuş normalizasyonu backend'de #39). */
export async function synthesizeTTS(text, { stripDisclaimer = true } = {}) {
  const res = await fetch("/multimodal/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ text, strip_disclaimer: stripDisclaimer }),
  });
  if (!res.ok) throw new Error(`TTS başarısız (HTTP ${res.status})`);
  return res.blob();
}

/** DELETE /ask/session/{id} — sunucu tarafı geçmişi + dilekçe PDF'i sil (KVKK).
 *  "Yeni sohbet"te çağrılır; fire-and-forget (hata kullanıcıyı durdurmaz). */
export async function clearSession(conversationId) {
  // Backend pattern: ^[A-Za-z0-9_-]+$, min_length=8 — geçersiz ID gönderme.
  if (!conversationId || conversationId.length < 8 || !/^[\w-]+$/.test(conversationId)) return;
  try {
    await fetch(`/ask/session/${encodeURIComponent(conversationId)}`, {
      method: "DELETE", headers: authHeaders(),
    });
  } catch { /* yoksay — temizlik en iyi çaba */ }
}

/**
 * POST /feedback — verilen cevap için 👍/👎 (+ opsiyonel serbest yorum).
 * Best-effort: çağıran .catch ile yutmalı (feedback kritik değil, UX'i bloklamaz).
 * conversationId yoksa (backend henüz id atamadıysa) ağ çağrısı yapılmaz → 422 önle.
 * @param {{conversationId:string, rating:"up"|"down", comment?:string|null, turnIndex?:number|null}} p
 */
export async function postFeedback({ conversationId, rating, comment = null, turnIndex = null }) {
  if (!conversationId) return { ok: false, skipped: true };
  const body = { conversation_id: conversationId, rating };
  if (comment) body.comment = comment;
  if (turnIndex != null) body.turn_index = turnIndex;
  const res = await fetch("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`feedback ${res.status}`);
  return res.json();
}

/** POST /emsal/full-text — bir kararın TAM metnini canlı getir (İlgili Kararlar paneli).
 *  Korpus kararları parçalı indeksliyor (tam metin yok) → istek üzerine resmi kaynaktan
 *  (Bedesten/UYAP/Anayasa) çekilir. Döner {text, cached, error}; text boşsa error dolu. */
export async function fetchFullDecision({ source_url = "", source_id = "", court = "" } = {}, signal) {
  const res = await fetch("/emsal/full-text", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ source_url, source_id, court }),
    signal,
  });
  if (!res.ok) throw new Error(`Tam metin getirilemedi (HTTP ${res.status})`);
  return res.json();
}

/** Backend ayakta mı? (mock fallback kararı için). */
export async function backendHealthy() {
  try {
    const res = await fetch("/health", { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch { return false; }
}
