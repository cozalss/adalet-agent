/* ADALET backend client — SSE streaming + dilekçe + OCR.
   Vite dev proxy /ask,/api,/multimodal → FastAPI :8000. */

/** Auth token (davet kodu akışından). Şimdilik localStorage; yoksa header yok. */
function authHeaders() {
  const t = localStorage.getItem("adalet-token");
  return t ? { Authorization: `Bearer ${t}` } : {};
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

/* ---------- Kullanıcı tercihleri (/me/preferences) — cihazlar-arası senkron.
   Birincil kaynak localStorage (anonim çalışır); bu uçlar yalnız auth'lu (token
   var) kullanıcıda iş görür. Anonim → 401 (sessizce yutulur, yerel veri kalır). */

/** Token yoksa backend tercih senkronu anlamsız (anonim) → erken çık. */
function hasToken() {
  return !!localStorage.getItem("adalet-token");
}

/** GET /me/preferences — auth'lu kullanıcının sunucudaki tercihleri (yoksa null). */
export async function getPreferences() {
  if (!hasToken()) return null;
  try {
    const res = await fetch("/me/preferences", { headers: authHeaders() });
    if (!res.ok) return null; // 401 anonim / 404 yok → yerel veriyle devam
    return res.json();
  } catch { return null; }
}

/** PUT /me/preferences — tercihleri sunucuya yaz (best-effort, fire-and-forget). */
export async function putPreferences(prefs) {
  if (!hasToken()) return false;
  try {
    const res = await fetch("/me/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(prefs),
    });
    return res.ok;
  } catch { return false; }
}

/** DELETE /me/preferences — KVKK silme hakkı (sunucu kaydını temizle). */
export async function deletePreferences() {
  if (!hasToken()) return false;
  try {
    const res = await fetch("/me/preferences", { method: "DELETE", headers: authHeaders() });
    return res.ok;
  } catch { return false; }
}

/* ---------- Sohbet geçmişi (/me/conversations) — cihazlar-arası senkron.
   Birincil kaynak localStorage (anonim çalışır); bu uçlar yalnız auth'lu
   (token var) kullanıcıda iş görür. Anonim → 401 (sessizce yutulur). */

/** GET /me/conversations[?q=] — kullanıcının sohbet listesi (metadata) veya null. */
export async function listConversationsApi(q) {
  if (!hasToken()) return null;
  try {
    const url = q ? `/me/conversations?q=${encodeURIComponent(q)}` : "/me/conversations";
    const res = await fetch(url, { headers: authHeaders() });
    return res.ok ? res.json() : null;
  } catch { return null; }
}

/** GET /me/conversations/{id} — tek sohbetin tüm mesajları veya null. */
export async function getConversationApi(id) {
  if (!hasToken()) return null;
  try {
    const res = await fetch(`/me/conversations/${encodeURIComponent(id)}`, { headers: authHeaders() });
    return res.ok ? res.json() : null;
  } catch { return null; }
}

/** PUT /me/conversations/{id} — sohbeti kaydet (best-effort, fire-and-forget). */
export async function putConversationApi(id, body) {
  if (!hasToken()) return false;
  try {
    const res = await fetch(`/me/conversations/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch { return false; }
}

/** DELETE /me/conversations/{id} — sohbeti sil (silme hakkı). */
export async function deleteConversationApi(id) {
  if (!hasToken()) return false;
  try {
    const res = await fetch(`/me/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE", headers: authHeaders(),
    });
    return res.ok;
  } catch { return false; }
}

/** DELETE /me/conversations — TÜM geçmişi tek istekle sil (KVKK silme hakkı). */
export async function deleteAllConversationsApi() {
  if (!hasToken()) return false;
  try {
    const res = await fetch("/me/conversations", { method: "DELETE", headers: authHeaders() });
    return res.ok;
  } catch { return false; }
}

/** GET /me/files — "Dosyalarım" metadata listesi veya null. */
export async function listFilesApi() {
  if (!hasToken()) return null;
  try {
    const res = await fetch("/me/files", { headers: authHeaders() });
    return res.ok ? res.json() : null;
  } catch { return null; }
}

/** POST /me/files — OCR yükleme metadata kaydı (best-effort). */
export async function addFileApi(meta) {
  if (!hasToken()) return false;
  try {
    const res = await fetch("/me/files", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(meta),
    });
    return res.ok;
  } catch { return false; }
}

/** Backend ayakta mı? (mock fallback kararı için). */
export async function backendHealthy() {
  try {
    const res = await fetch("/health", { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch { return false; }
}
