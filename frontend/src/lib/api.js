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

  const dispatch = (event, data) => {
    switch (event) {
      case "node": handlers.onNode?.(data); break;
      case "triage": handlers.onTriage?.(data); break;
      case "clarify": handlers.onClarify?.(data); break;
      case "sources": handlers.onSources?.(data); break;
      case "drafting": handlers.onDrafting?.(data); break;
      case "verifying": handlers.onVerifying?.(data); break;
      case "timing": handlers.onTiming?.(data); break;
      case "final": handlers.onFinal?.(data); break;
      case "error": handlers.onError?.(data); break;
      default: break;
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
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
            console.warn("[ADALET] SSE frame parse edilemedi:", event, err);
            handlers.onError?.({ detail: "Yanıt çözümlenemedi, lütfen tekrar deneyin." });
          }
        }
      }
    }
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
  if (!res.ok) throw new Error(`OCR başarısız (HTTP ${res.status})`);
  return res.json(); // {text, engine, n_chars, ...}
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

/** Backend ayakta mı? (mock fallback kararı için). */
export async function backendHealthy() {
  try {
    const res = await fetch("/health", { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch { return false; }
}
