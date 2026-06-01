-- ADALET — Supabase şeması (auth + sohbet geçmişi + tercihler).
-- Supabase Dashboard → SQL Editor'e yapıştır + RUN. (auth.users built-in'dir.)
-- Güvenlik: RLS ile her kullanıcı YALNIZ kendi satırlarını görür/yazar (IDOR'a kapalı).

-- ============================ profiles (tercihler) ============================
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
create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text default '',
  domain text default '',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists conversations_user_updated on public.conversations (user_id, updated_at desc);
alter table public.conversations enable row level security;
create policy "conv_select_own" on public.conversations for select using (auth.uid() = user_id);
create policy "conv_insert_own" on public.conversations for insert with check (auth.uid() = user_id);
create policy "conv_update_own" on public.conversations for update using (auth.uid() = user_id);
create policy "conv_delete_own" on public.conversations for delete using (auth.uid() = user_id);

-- ============================ messages ============================
create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  turn_index int default 0,
  role text default 'user',                    -- user | assistant
  content text default '',
  citations jsonb default '[]'::jsonb,
  confidence numeric default 0,
  created_at timestamptz default now()
);
create index if not exists messages_conv on public.messages (conversation_id, turn_index);
alter table public.messages enable row level security;
-- Mesaja erişim, sahibi olunan sohbete bağlı (RLS join).
create policy "msg_select_own" on public.messages for select
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid()));
create policy "msg_insert_own" on public.messages for insert
  with check (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid()));
create policy "msg_delete_own" on public.messages for delete
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = auth.uid()));

-- ============================ uploaded_files (Dosyalarım) ============================
create table if not exists public.uploaded_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  conversation_id uuid,
  filename text default '',
  ocr_engine text default '',
  n_chars int default 0,
  pii_flag boolean default false,
  uploaded_at timestamptz default now()
);
create index if not exists files_user on public.uploaded_files (user_id, uploaded_at desc);
alter table public.uploaded_files enable row level security;
create policy "files_select_own" on public.uploaded_files for select using (auth.uid() = user_id);
create policy "files_insert_own" on public.uploaded_files for insert with check (auth.uid() = user_id);
create policy "files_delete_own" on public.uploaded_files for delete using (auth.uid() = user_id);
