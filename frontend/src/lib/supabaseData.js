/* ADALET — Supabase veri katmanı (sohbet geçmişi + tercihler).

   "Tam geçiş" (v2.2): kayıtlı kullanıcının sohbet geçmişi ve tercihleri artık
   eski FastAPI /me/* uçları yerine DOĞRUDAN Supabase'e (Postgres + RLS) yazılır.
   supabase-js her isteğe oturum JWT'sini ekler; RLS sahipliği DB seviyesinde
   zorlar (auth.uid() = user_id) — IDOR'a kapalı, owner-check kodu gerekmez.

   Misafir / oturumsuz: her fonksiyon sessiz no-op döner (null/false). Birincil
   kaynak yine tarayıcı localStorage'dır; Supabase yalnız cihazlar-arası senkron. */
import { supabase } from "./supabase.js";
import { turnsToMessages, messagesToTurns } from "./conversationUtils.js";

const MAX_CONVERSATIONS = 100; // en yeni N sohbeti senkronla (sınırsız büyümeyi önle)

/** Aktif oturumun kullanıcısı (yerel — ağ yok) veya null (misafir). */
async function sessionUser() {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data?.session?.user || null;
}

/** Senkron hatası best-effort ama SESSİZ DEĞİL — kullanıcı veri kaybını fark
 *  edebilsin diye konsola yaz (toast/banner üst katmanda ele alınabilir). */
function logSync(op, error) {
  // eslint-disable-next-line no-console
  console.warn(`[adalet] Supabase senkron başarısız (${op}):`, error?.message || error);
}

/** Oturum değişiminde (giriş/çıkış) tetikle — hook'lar yeniden senkronlar.
 *  @returns {() => void} abonelik iptal fonksiyonu */
export function onAuthChange(cb) {
  if (!supabase) return () => {};
  const { data } = supabase.auth.onAuthStateChange((event) => {
    if (event === "SIGNED_IN" || event === "SIGNED_OUT") cb(event);
  });
  return () => data.subscription.unsubscribe();
}

/* ============================ Sohbet geçmişi ============================ */

/** Tüm sohbetleri + mesajlarını çek → { [id]: rec } haritası (yoksa null). */
export async function loadConversationsSb() {
  if (!(await sessionUser())) return null;
  const { data, error } = await supabase
    .from("conversations")
    .select("id, title, domain, created_at, updated_at, messages(turn_index, role, content, citations, confidence)")
    .order("updated_at", { ascending: false })
    .limit(MAX_CONVERSATIONS);
  if (error || !data) return null;
  const map = {};
  for (const c of data) {
    map[c.id] = {
      id: c.id,
      title: c.title || "",
      domain: c.domain || "",
      createdAt: c.created_at,
      updatedAt: c.updated_at,
      turns: messagesToTurns(c.messages || [], c.domain || ""),
      files: [],
    };
  }
  return map;
}

/** Sohbeti kaydet/güncelle: conversation upsert + mesaj replace TEK TRANSACTION
 *  (save_conversation RPC). Atomik → delete/insert arası hata = mesaj kaybı YOK.
 *  RPC SECURITY INVOKER + RLS: başka kullanıcının id'sine yazma → rollback. */
export async function upsertConversationSb(id, { title, domain, turns }) {
  if (!id || !(await sessionUser())) return false;
  const rows = turnsToMessages(turns).map((m) => ({
    turn_index: m.turn_index,
    role: m.role,
    content: m.content,
    citations: m.citations || [],
    confidence: m.confidence || 0,
  }));
  const { error } = await supabase.rpc("save_conversation", {
    p_id: id, p_title: title || "", p_domain: domain || "", p_rows: rows,
  });
  if (error) { logSync("save_conversation", error); return false; }
  return true;
}

/** Sohbeti sil (mesajlar + dosya kayıtları ON DELETE CASCADE ile gider). */
export async function deleteConversationSb(id) {
  if (!id || !(await sessionUser())) return false;
  const { error } = await supabase.from("conversations").delete().eq("id", id);
  if (error) { logSync("deleteConversation", error); return false; }
  return true;
}

/** TÜM geçmişi sil ("tüm verilerimi sil"). RLS zaten kullanıcıya kısıtlar;
 *  PostgREST filtresiz DELETE'i reddettiği için user_id ile filtreliyoruz. */
export async function deleteAllConversationsSb() {
  const u = await sessionUser();
  if (!u) return false;
  const { error } = await supabase.from("conversations").delete().eq("user_id", u.id);
  if (error) { logSync("deleteAllConversations", error); return false; }
  return true;
}

/* ============================ Tercihler (profiles) ============================ */

/** Kullanıcının profil (tercih) satırı → sunucu şekli veya null. */
export async function loadPrefsSb() {
  const u = await sessionUser();
  if (!u) return null;
  const { data, error } = await supabase
    .from("profiles")
    .select("display_name, text_scale, reduce_motion, high_contrast, preferred_domains")
    .eq("id", u.id)
    .maybeSingle();
  if (error || !data) return null;
  return data;
}

/** Tercihleri profile yaz (upsert — trigger satırı kayıtta zaten oluşturmuş olabilir). */
export async function upsertPrefsSb(payload) {
  const u = await sessionUser();
  if (!u) return false;
  const { error } = await supabase
    .from("profiles")
    .upsert({ id: u.id, ...payload, updated_at: new Date().toISOString() }, { onConflict: "id" });
  if (error) { logSync("upsertPrefs", error); return false; }
  return true;
}

/** Tercihleri varsayılana döndür (profil satırı auth'a bağlı kalır — silme yerine reset). */
export async function clearPrefsSb() {
  return upsertPrefsSb({
    display_name: "", text_scale: "normal", reduce_motion: false,
    high_contrast: false, preferred_domains: [],
  });
}

/* ============================ Dosyalarım (uploaded_files) ============================ */

/** OCR yükleme metadata kaydı (best-effort; misafirde no-op). Belge METNİ saklanmaz. */
export async function addFileSb(meta) {
  if (!(await sessionUser())) return false;
  const { error } = await supabase.from("uploaded_files").insert({
    conversation_id: meta.conversation_id || null,
    filename: meta.filename || "",
    ocr_engine: meta.ocr_engine || "",
    n_chars: meta.n_chars || 0,
    pii_flag: !!meta.pii_flag,
  });
  if (error) { logSync("addFile", error); return false; }
  return true;
}
