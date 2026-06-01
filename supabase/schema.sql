-- ADALET — Supabase şeması (auth + sohbet geçmişi + tercihler).
-- Supabase Dashboard → SQL Editor'e yapıştır + RUN. (auth.users built-in'dir.)
-- Güvenlik: RLS ile her kullanıcı YALNIZ kendi satırlarını görür/yazar (IDOR'a kapalı).
--
-- TASARIM NOTU (conversation id = TEXT):
--   Uygulamanın conversation_id'si backend'de uuid4().hex (32 hex, tiresiz) üretilir
--   ve /ask/stream session + dilekçe indirme bu tam string'e bağlıdır. Postgres'in
--   uuid tipi bunu dashed forma çevirip geri döndürür → localStorage (hex) ile DB
--   (dashed) eşleşmez. Bu yüzden conversation id'ler TEXT: backend string'iyle birebir.
--   (RLS user_id/uuid üzerinden — id tipi güvenliği etkilemez.)
--
-- SERTLEŞTİRME (3-ajan incelemesi, 2026-06):
--   * Tüm RLS policy'lerde (select auth.uid()) — per-row değil per-query (Supabase
--     initPlan optimizasyonu; yüklü tabloda ciddi hızlanma).
--   * CHECK constraint'ler (role/text_scale/turn_index/confidence/n_chars) — DB
--     seviyesinde veri bütünlüğü.
--   * uploaded_files → conversations FK (ON DELETE CASCADE) — orphan kayıt yok.
--   * conversations.updated_at için DB trigger — client clock skew'a bağlı değil.
--   * save_conversation() RPC — conversation upsert + mesaj replace TEK TRANSACTION
--     (atomik; yarı-yazma / mesaj kaybı yok). SECURITY INVOKER → RLS korur.
--   * handle_new_user search_path = '' (boş) + tam-nitelikli referans (injection sert).
--
-- IDEMPOTENT: tablolar boşken yeniden çalıştırmak güvenlidir (drop ... cascade).
-- UYARI: Aşağıdaki conversations/messages/uploaded_files DROP'ları PRODUCTION'da
--   (gerçek veri varken) ÇALIŞTIRILMAZ — yalnız ilk kurulum / tam sıfırlama içindir.

-- ============================ profiles (tercihler) ============================
-- id = auth.users(id) (uuid — Supabase'in kendi kullanıcı anahtarı, DEĞİŞMEZ).
-- profiles korunur (drop yok): kullanıcı tercih satırları kaybolmasın.
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text default '',
  text_scale text default 'normal',           -- compact | normal | large
  reduce_motion boolean default false,
  high_contrast boolean default false,
  preferred_domains text[] default '{}',
  updated_at timestamptz default now()
);
alter table public.profiles drop constraint if exists profiles_text_scale_check;
alter table public.profiles add constraint profiles_text_scale_check
  check (text_scale in ('compact', 'normal', 'large'));
alter table public.profiles enable row level security;
drop policy if exists "profiles_select_own" on public.profiles;
drop policy if exists "profiles_insert_own" on public.profiles;
drop policy if exists "profiles_update_own" on public.profiles;
drop policy if exists "profiles_delete_own" on public.profiles;
create policy "profiles_select_own" on public.profiles for select using ((select auth.uid()) = id);
create policy "profiles_insert_own" on public.profiles for insert with check ((select auth.uid()) = id);
create policy "profiles_update_own" on public.profiles for update using ((select auth.uid()) = id);
-- "hesabımı sil" akışı için (ileride) — kullanıcı kendi profilini silebilir.
create policy "profiles_delete_own" on public.profiles for delete using ((select auth.uid()) = id);

-- Yeni kayıtta otomatik profil satırı (Supabase standart deseni).
-- search_path = '' + tam-nitelikli referans → search_path injection'a kapalı.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'name', ''))
  on conflict (id) do nothing;
  return new;
end; $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users for each row execute function public.handle_new_user();

-- updated_at otomatik tazeleme (client clock'a güvenme) — paylaşılan trigger fn.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end; $$;

-- ============================ conversations ============================
-- id = TEXT: uygulamanın conversation_id'si (backend uuid4().hex) — bkz. üst not.
drop table if exists public.messages cascade;
drop table if exists public.uploaded_files cascade;
drop table if exists public.conversations cascade;

create table public.conversations (
  id text primary key,                         -- backend conversation_id (uuid4().hex)
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text default '',
  domain text default '',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index conversations_user_updated on public.conversations (user_id, updated_at desc);
drop trigger if exists set_conversations_updated_at on public.conversations;
create trigger set_conversations_updated_at
  before update on public.conversations for each row execute function public.set_updated_at();
alter table public.conversations enable row level security;
create policy "conv_select_own" on public.conversations for select using ((select auth.uid()) = user_id);
create policy "conv_insert_own" on public.conversations for insert with check ((select auth.uid()) = user_id);
create policy "conv_update_own" on public.conversations for update using ((select auth.uid()) = user_id);
create policy "conv_delete_own" on public.conversations for delete using ((select auth.uid()) = user_id);

-- ============================ messages ============================
-- id = uuid (Supabase üretir, iç anahtar). messages KASITLI immutable: UPDATE
-- policy YOK; güncelleme save_conversation() RPC'sinde delete+insert ile yapılır.
-- UNIQUE(conversation_id, turn_index): aynı tur iki kez yazılamaz (idempotent).
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id text not null references public.conversations(id) on delete cascade,
  turn_index int not null default 0,
  role text not null default 'user',           -- user | assistant
  content text default '',
  citations jsonb default '[]'::jsonb,
  confidence numeric default 0,
  created_at timestamptz default now(),
  constraint messages_role_check check (role in ('user', 'assistant')),
  constraint messages_turn_index_check check (turn_index >= 0),
  constraint messages_confidence_check check (confidence >= 0 and confidence <= 100),
  constraint messages_conv_turn_unique unique (conversation_id, turn_index)
);
create index messages_conv on public.messages (conversation_id, turn_index);
alter table public.messages enable row level security;
-- Mesaja erişim, sahibi olunan sohbete bağlı (RLS join).
create policy "msg_select_own" on public.messages for select
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid())));
create policy "msg_insert_own" on public.messages for insert
  with check (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid())));
create policy "msg_delete_own" on public.messages for delete
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid())));

-- ============================ uploaded_files (Dosyalarım) ============================
-- conversation_id → conversations FK (ON DELETE CASCADE): sohbet silinince dosya
-- metadata'sı da gider (orphan yok). NULL serbest (sohbetsiz yükleme).
create table public.uploaded_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  conversation_id text references public.conversations(id) on delete cascade,
  filename text default '',
  ocr_engine text default '',
  n_chars int default 0,
  pii_flag boolean default false,
  uploaded_at timestamptz default now(),
  constraint uploaded_files_n_chars_check check (n_chars >= 0)
);
create index files_user on public.uploaded_files (user_id, uploaded_at desc);
create index files_conv on public.uploaded_files (conversation_id);
alter table public.uploaded_files enable row level security;
create policy "files_select_own" on public.uploaded_files for select using ((select auth.uid()) = user_id);
create policy "files_insert_own" on public.uploaded_files for insert with check ((select auth.uid()) = user_id);
create policy "files_delete_own" on public.uploaded_files for delete using ((select auth.uid()) = user_id);

-- ============================ save_conversation() RPC ============================
-- Conversation upsert + mesaj replace'i TEK TRANSACTION'da yapar (atomik): delete
-- ile insert arası hata olursa tümü geri alınır → mesaj kaybı YOK.
-- SECURITY INVOKER (varsayılan): çağıran kullanıcı olarak koşar → RLS her satırda
-- sahipliği zorlar. Başka kullanıcının id'sine yazma denemesi RLS ihlali → rollback.
-- p_rows: [{turn_index,role,content,citations,confidence}, ...] (jsonb dizisi).
create or replace function public.save_conversation(
  p_id text, p_title text, p_domain text, p_rows jsonb
) returns void language plpgsql security invoker set search_path = '' as $$
begin
  insert into public.conversations (id, title, domain)
  values (p_id, coalesce(p_title, ''), coalesce(p_domain, ''))
  on conflict (id) do update
    set title = excluded.title, domain = excluded.domain
    where public.conversations.user_id = (select auth.uid());

  delete from public.messages where conversation_id = p_id;

  insert into public.messages (conversation_id, turn_index, role, content, citations, confidence)
  select p_id,
         coalesce((r->>'turn_index')::int, 0),
         coalesce(r->>'role', 'user'),
         coalesce(r->>'content', ''),
         coalesce(r->'citations', '[]'::jsonb),
         coalesce((r->>'confidence')::numeric, 0)
  from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb)) as r;
end; $$;
