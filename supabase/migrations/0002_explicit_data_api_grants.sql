-- ADALET — Incremental migration 0002: explicit Supabase Data API grants (2026-06)
-- ------------------------------------------------------------------------
-- Supabase changelog: new projects no longer expose public tables to Data API
-- automatically. Frontend uses supabase-js for conversations/profiles/files, so
-- authenticated role needs explicit table/RPC grants in addition to RLS.
--
-- Safe to apply on existing projects. No data mutation.

begin;

grant usage on schema public to authenticated;

revoke all on table public.profiles from public, anon, authenticated;
revoke all on table public.conversations from public, anon, authenticated;
revoke all on table public.messages from public, anon, authenticated;
revoke all on table public.uploaded_files from public, anon, authenticated;

grant select, insert, update, delete on table public.profiles to authenticated;
grant select, insert, update, delete on table public.conversations to authenticated;
grant select, insert, update, delete on table public.messages to authenticated;
grant select, insert, update, delete on table public.uploaded_files to authenticated;

revoke execute on function public.save_conversation(text, text, text, jsonb) from public;
revoke execute on function public.save_conversation(text, text, text, jsonb) from anon;
grant execute on function public.save_conversation(text, text, text, jsonb) to authenticated;

commit;
