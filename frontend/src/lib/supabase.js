/* ADALET — Supabase istemcisi (auth + sohbet geçmişi).

   URL + anon key build-time env'den (VITE_SUPABASE_*). Ayarlanmamışsa client null
   → uygulama çökmez ama GİRİŞ KULLANILAMAZ (misafir modu yok; AuthPage env-yok
   uyarısı gösterir). Kurulum: ../../SUPABASE_SETUP.md */
import { createClient } from "@supabase/supabase-js";

const URL = import.meta.env.VITE_SUPABASE_URL;
const ANON = import.meta.env.VITE_SUPABASE_ANON_KEY;

/** Supabase yapılandırılmış mı? (env iki değeri de var) */
export const supabaseEnabled = !!(URL && ANON);

/** Tek paylaşılan istemci (env yoksa null — giriş kullanılamaz). */
export const supabase = supabaseEnabled
  ? createClient(URL, ANON, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    })
  : null;
