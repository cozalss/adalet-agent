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
-- IDEMPOTENT: tablolar boşken yeniden çalıştırmak güvenlidir (drop ... cascade).

-- ============================ profiles (tercihler) ============================
-- id = auth.users(id) (uuid — Supabase'in kendi kullanıcı anahtarı, DEĞİŞMEZ).
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text default '',
  text_scale text default 'normal',           -- compact | normal | large
  reduce_motion boolean default false,
  high_contrast boolean default false,
  preferred_domains text[] default '{}',
  updated_at timestamptz default now()
);
alter table public.profiles enable row level security;
drop policy if exists "profiles_select_own" on public.profiles;
drop policy if exists "profiles_insert_own" on public.profiles;
drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_select_own" on public.profiles for select using (auth.uid() = id);
create policy "profiles_insert_own" on public.profiles for insert with check (auth.uid() = id);
create policy "profiles_update_own" on public.profiles for update using (auth.uid() = id);

-- Yeni kayıtta otomatik profil satırı (Supabase standart deseni).
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'name', ''))
  on conflict (id) do nothing;
  return new;
end; $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users for each row execute function public.handle_new_user();

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
alter table public.conversations enable row level security;
create policy "conv_select_own" on public.conversations for select using (auth.uid() = user_id);
create policy "conv_insert_own" on public.conversations for insert with check (auth.uid() = user_id);
create policy "conv_update_own" on public.conversations for update using (auth.uid() = user_id);
create policy "conv_delete_own" on public.conversations for delete using (auth.uid() = user_id);

-- ============================ messages ============================
-- id = uuid (Supabase üretir, iç anahtar — uygulama mesajı tekil id ile referanslamaz).
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id text not null references public.conversations(id) on delete cascade,
  turn_index int default 0,
  role text default 'user',                    -- user | assistant
  content text default '',
  citations jsonb default '[]'::jsonb,
  confidence numeric default 0,
  created_at timestamptz default now()
);
create index messages_conv on public.messages (conversation_id, turn_index);
alter table public.messages enable row level security;
-- Mesaja erişim, sahibi olunan sohbete bağlı (RLS join).
create policy "msg_select_own" on public.messages for select
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid()));
create policy "msg_insert_own" on public.messages for insert
  with check (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid()));
create policy "msg_delete_own" on public.messages for delete
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid()));

-- ============================ uploaded_files (Dosyalarım) ============================
create table public.uploaded_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  conversation_id text,                        -- conversations.id (text) ile aynı uzay
  filename text default '',
  ocr_engine text default '',
  n_chars int default 0,
  pii_flag boolean default false,
  uploaded_at timestamptz default now()
);
create index files_user on public.uploaded_files (user_id, uploaded_at desc);
alter table public.uploaded_files enable row level security;
create policy "files_select_own" on public.uploaded_files for select using (auth.uid() = user_id);
create policy "files_insert_own" on public.uploaded_files for insert with check (auth.uid() = user_id);
create policy "files_delete_own" on public.uploaded_files for delete using (auth.uid() = user_id);
