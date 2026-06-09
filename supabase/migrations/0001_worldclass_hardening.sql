-- ADALET — Incremental migration 0001: world-class hardening (2026-06)
-- ------------------------------------------------------------------------
-- MEVCUT bir projeye BİR KEZ uygulanır: Supabase Dashboard → SQL Editor → RUN
-- (veya MCP apply_migration). schema.sql tam-reset scriptidir; bu dosya ise
-- VERİ VARKEN güvenle çalışan artımlı değişikliktir (bkz. docs/DB_OPERATIONS.md).
--
-- GÜVENLİ: veri değişmez, tamamen geri alınabilir. Canlı DB'yi sertleştirilmiş
-- schema.sql ile hizalar. Kaynak: Supabase advisor denetimi (security+performance)
-- + RLS rol kapsamı incelemesi.
--
--   1) handle_new_user(): SECURITY DEFINER fn /rest/v1/rpc ile çağrılabiliyordu
--      → anon+authenticated için EXECUTE geri alındı. Trigger YİNE çalışır
--      (auth.users insert'te owner olarak; EXECUTE grant'i trigger'ı etkilemez).
--   2) set_updated_at(): search_path pinlenmemişti → '' sabitlendi (yalnız
--      pg_catalog.now() kullanır, '' ile sorunsuz).
--   3) messages_conv: messages_conv_turn_unique (UNIQUE, aynı kolonlar) ile
--      birebir kopya indeks → düşürüldü (yazma/disk maliyeti azalır).
--   4) 15 RLS policy {public} → {authenticated} rolüne kapsandı. anon zaten
--      auth.uid()=null ile 0 satır eşliyordu; bu, anon trafiğini kısa-devre eder.

begin;

-- 1) Security: revoke RPC-exposed EXECUTE on the SECURITY DEFINER auth trigger fn.
revoke execute on function public.handle_new_user() from public;
revoke execute on function public.handle_new_user() from anon;
revoke execute on function public.handle_new_user() from authenticated;

-- 2) Security: pin search_path on the updated_at trigger fn.
alter function public.set_updated_at() set search_path = '';

-- 3) Performance: drop duplicate index (UNIQUE constraint already covers it).
drop index if exists public.messages_conv;

-- 4) Hardening: scope owner-only RLS policies to the authenticated role.
alter policy conv_select_own     on public.conversations  to authenticated;
alter policy conv_insert_own     on public.conversations  to authenticated;
alter policy conv_update_own     on public.conversations  to authenticated;
alter policy conv_delete_own     on public.conversations  to authenticated;
alter policy msg_select_own      on public.messages       to authenticated;
alter policy msg_insert_own      on public.messages       to authenticated;
alter policy msg_update_deny     on public.messages       to authenticated;
alter policy msg_delete_own      on public.messages       to authenticated;
alter policy profiles_select_own on public.profiles       to authenticated;
alter policy profiles_insert_own on public.profiles       to authenticated;
alter policy profiles_update_own on public.profiles       to authenticated;
alter policy profiles_delete_own on public.profiles       to authenticated;
alter policy files_select_own    on public.uploaded_files to authenticated;
alter policy files_insert_own    on public.uploaded_files to authenticated;
alter policy files_update_deny   on public.uploaded_files to authenticated;
alter policy files_delete_own    on public.uploaded_files to authenticated;

commit;
