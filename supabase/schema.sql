-- ADALET — Supabase şeması (auth + sohbet geçmişi + tercihler).
-- Supabase Dashboard → SQL Editor'e yapıştır + RUN. (auth.users built-in'dir.)
-- Güvenlik: RLS ile her kullanıcı YALNIZ kendi satırlarını görür/yazar (IDOR'a kapalı).
--
-- TASARIM NOTU (conversation id = TEXT):
--   conversation_id backend'de uuid4().hex; uuid tipi dashed'e çevirip localStorage/
--   backend-session eşleşmesini bozuyordu. Bu yüzden TEXT (backend string'iyle birebir).
--
-- SERTLEŞTİRME — iki tur 3-ajan incelemesi (2026-06):
--   * Tüm RLS policy'lerde (select auth.uid()) — per-query (initPlan) optimizasyonu.
--   * save_conversation() RPC: TEK TRANSACTION (atomik) + SAHİPLİK FAIL-FAST (başka
--     kullanıcının id'sine yazma → sessiz no-op DEĞİL, açık hata) + PAYLOAD LİMİTİ
--     (max 200 satır / 1MB — DoS/şişme önler). SECURITY INVOKER → RLS korur.
--   * BOYUT CHECK'leri (content/citations/title/domain/filename/display_name) — disk
--     şişirme vektörünü kapatır. confidence numeric(5,2).
--   * profiles + conversations updated_at DB trigger (client clock'a güvenme).
--   * messages & uploaded_files: EXPLICIT deny-update policy (immutable niyeti SQL'de;
--     RLS kapansa bile alarm). conversations/profiles update'te WITH CHECK (user_id transferi engel).
--   * handle_new_user: search_path='' + EXCEPTION bloğu (sessiz başarısızlık yok, fail-closed).
--   * PII: messages.content kullanıcı hukuki metni içerebilir (TCKN/IBAN). Supabase cloud
--     AES-256 disk şifrelemesi sağlar; backend pii_flag ile maskeleme önerilir.
--
-- ⚠️ MIGRATION GÜVENLİĞİ: Aşağıdaki conv/msg/files DROP'ları YALNIZ ilk kurulum / tam
--   sıfırlama içindir. Tablolarda VERİ varsa script bir GUARD ile DURUR (veri kaybını
--   önler). Artımlı değişiklik için ayrı versiyonlu migration kullan (bkz. docs/DB_OPERATIONS.md).

-- ============================ profiles (tercihler) ============================
-- id = auth.users(id) (uuid — Supabase kullanıcı anahtarı, DEĞİŞMEZ). DROP YOK (korunur).
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
alter table public.profiles drop constraint if exists profiles_displayname_len;
alter table public.profiles add constraint profiles_displayname_len
  check (char_length(display_name) <= 200);

-- updated_at otomatik tazeleme (client clock'a güvenme) — paylaşılan trigger fn.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end; $$;
drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
  before update on public.profiles for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
drop policy if exists "profiles_select_own" on public.profiles;
drop policy if exists "profiles_insert_own" on public.profiles;
drop policy if exists "profiles_update_own" on public.profiles;
drop policy if exists "profiles_delete_own" on public.profiles;
create policy "profiles_select_own" on public.profiles for select using ((select auth.uid()) = id);
create policy "profiles_insert_own" on public.profiles for insert with check ((select auth.uid()) = id);
create policy "profiles_update_own" on public.profiles for update
  using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
-- "hesabımı sil" akışı için (Edge Function ileride — bkz. docs/DB_OPERATIONS.md).
create policy "profiles_delete_own" on public.profiles for delete using ((select auth.uid()) = id);

-- Yeni kayıtta otomatik profil satırı. search_path='' + EXCEPTION (fail-closed + loglu).
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'name', ''))
  on conflict (id) do nothing;
  return new;
exception when others then
  -- Profil oluşturma hatası: logla + yeniden fırlat → auth.users insert'i de rollback
  -- (kullanıcı 'kayıt başarısız' görür, tekrar dener). Sessiz veri bozulması YOK.
  raise warning 'handle_new_user profil hatasi (user_id=%): %', new.id, sqlerrm;
  raise;
end; $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users for each row execute function public.handle_new_user();

-- ============================ MIGRATION GUARD ============================
-- Yıkıcı DROP'lardan önce: tablolarda VERİ varsa DUR (kazara prod re-run = veri kaybı önle).
do $$
begin
  if exists (select 1 from public.conversations limit 1)
     or exists (select 1 from public.messages limit 1) then
    raise exception 'GUVENLIK DURDURMA: conversations/messages BOS DEGIL — yikici kurulum scripti veri varken calistirilamaz. Artimlik degisiklik icin versiyonlu migration kullan (docs/DB_OPERATIONS.md).';
  end if;
exception
  when undefined_table then null; -- ilk kurulum: tablolar henuz yok → sorun degil, devam et
end $$;

-- ============================ conversations ============================
drop table if exists public.messages cascade;
drop table if exists public.uploaded_files cascade;
drop table if exists public.conversations cascade;

create table public.conversations (
  id text primary key,                         -- backend conversation_id (uuid4().hex)
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text default '',
  domain text default '',
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  constraint conv_title_len check (char_length(title) <= 500),
  constraint conv_domain_len check (char_length(domain) <= 64)
);
create index conversations_user_updated on public.conversations (user_id, updated_at desc);
-- messages RLS join'i (EXISTS c.id=conversation_id AND c.user_id=uid) index-only scan yapsın.
create index conversations_id_user on public.conversations (id, user_id);
drop trigger if exists set_conversations_updated_at on public.conversations;
create trigger set_conversations_updated_at
  before update on public.conversations for each row execute function public.set_updated_at();
alter table public.conversations enable row level security;
create policy "conv_select_own" on public.conversations for select using ((select auth.uid()) = user_id);
create policy "conv_insert_own" on public.conversations for insert with check ((select auth.uid()) = user_id);
create policy "conv_update_own" on public.conversations for update
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "conv_delete_own" on public.conversations for delete using ((select auth.uid()) = user_id);

-- ============================ messages ============================
-- id = uuid (Supabase üretir). KASITLI immutable: save_conversation delete+insert ile
-- tazeler → UPDATE açıkça reddedilir (deny policy). UNIQUE(conv,turn): tur tekilliği.
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id text not null references public.conversations(id) on delete cascade,
  turn_index int not null default 0,
  role text not null default 'user',           -- user | assistant
  content text default '',
  citations jsonb default '[]'::jsonb,
  confidence numeric(5,2) default 0,
  created_at timestamptz default now(),
  constraint messages_role_check check (role in ('user', 'assistant')),
  constraint messages_turn_index_check check (turn_index >= 0),
  constraint messages_confidence_check check (confidence >= 0 and confidence <= 100),
  constraint messages_content_len check (char_length(content) <= 100000),
  constraint messages_citations_len check (jsonb_array_length(citations) <= 100),
  constraint messages_conv_turn_unique unique (conversation_id, turn_index)
);
create index messages_conv on public.messages (conversation_id, turn_index);
alter table public.messages enable row level security;
create policy "msg_select_own" on public.messages for select
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid())));
create policy "msg_insert_own" on public.messages for insert
  with check (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid())));
create policy "msg_delete_own" on public.messages for delete
  using (exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid())));
-- EXPLICIT deny: messages immutable (UPDATE hiçbir satırı kapsamaz → tüm UPDATE reddedilir).
create policy "msg_update_deny" on public.messages for update using (false);

-- ============================ uploaded_files (Dosyalarım) ============================
create table public.uploaded_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  conversation_id text references public.conversations(id) on delete cascade,
  filename text default '',
  ocr_engine text default '',
  n_chars int default 0,
  pii_flag boolean default false,
  uploaded_at timestamptz default now(),
  constraint uploaded_files_n_chars_check check (n_chars >= 0),
  constraint files_filename_len check (char_length(filename) <= 500)
);
create index files_user on public.uploaded_files (user_id, uploaded_at desc);
create index files_conv on public.uploaded_files (conversation_id);
alter table public.uploaded_files enable row level security;
create policy "files_select_own" on public.uploaded_files for select using ((select auth.uid()) = user_id);
create policy "files_insert_own" on public.uploaded_files for insert with check ((select auth.uid()) = user_id);
create policy "files_delete_own" on public.uploaded_files for delete using ((select auth.uid()) = user_id);
-- EXPLICIT deny: uploaded_files metadata immutable (yalnız insert/delete).
create policy "files_update_deny" on public.uploaded_files for update using (false);

-- ============================ save_conversation() RPC ============================
-- Conversation upsert + mesaj replace TEK TRANSACTION (atomik): mesaj kaybı yok.
-- SECURITY INVOKER → RLS sahipliği her satırda zorlar. p_rows: [{turn_index,role,
-- content,citations,confidence}, ...]. SAHİPLİK FAIL-FAST + PAYLOAD LİMİTİ ile sertleştirildi.
create or replace function public.save_conversation(
  p_id text, p_title text, p_domain text, p_rows jsonb
) returns void language plpgsql security invoker set search_path = '' as $$
declare
  v_count int;
begin
  -- (1) Sahiplik fail-fast: başka kullanıcının id'sine yazma → AÇIK hata (sessiz no-op değil).
  if exists (select 1 from public.conversations c
             where c.id = p_id and c.user_id <> (select auth.uid())) then
    raise exception 'forbidden: bu conversation baska kullaniciya ait' using errcode = '42501';
  end if;

  -- (2) Payload sınırı (DoS/şişme): max 200 satır + max 1MB.
  v_count := jsonb_array_length(coalesce(p_rows, '[]'::jsonb));
  if v_count > 200 then
    raise exception 'p_rows cok uzun: % satir (max 200)', v_count;
  end if;
  if octet_length(coalesce(p_rows, '[]'::jsonb)::text) > 1048576 then
    raise exception 'p_rows cok buyuk (max 1MB)';
  end if;

  -- (3) Conversation upsert (sahiplik garanti; user_id DEFAULT auth.uid(); RLS de korur).
  insert into public.conversations (id, title, domain)
  values (p_id, coalesce(p_title, ''), coalesce(p_domain, ''))
  on conflict (id) do update
    set title = excluded.title, domain = excluded.domain;

  -- (4) Mesajları tazele: önce sil, sonra ekle (atomik — yarı-yazma yok).
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
