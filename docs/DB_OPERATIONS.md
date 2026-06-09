# ADALET — Supabase DB Operasyon Runbook'u

> Şema + RLS + RPC tarafı **production-grade** (iki tur 3-ajan incelemesi + canlı doğrulama;
> bkz. `supabase/schema.sql`). Bu dosya derin denetimin ortaya çıkardığı **operasyonel**
> boşlukları ve kararları belgeler — çoğu SQL değil, runbook/yapılandırma işidir.

## 1. Yedekleme & felaket kurtarma (KRİTİK — lansman öncesi şart)
Supabase **Free tier'da otomatik yedek YOK**. Hukuki veri için "veri kaybı = kabul edilemez".
- **Self-host (Hetzner compose) — ARTIK OTOMATİK:** `infra/deploy/hetzner-init.sh` (denetim #10)
  günlük pg_dump cron'u kurar (`adalet-postgres` → `/var/backups/adalet/postgres/`, gzip, 7-gün
  retention) + Qdrant snapshot (best-effort, corpus re-seed edilebilir). **Off-host kopya** (R2/S3)
  ve **restore testi** hâlâ elle yapılmalı (aşağıdaki uyarı).
- **Supabase (managed) için kısa vade:** GitHub Actions schedule veya VPS cron ile günlük `pg_dump`
  → şifreli olarak ayrı kovaya (R2/S3). Connection string secret'tan; DB şifresini komuta gömme.
- **Orta vade (lansman):** Supabase **Pro** + **PITR add-on** (7 gün geri-sarma).
- **Restore'u TEST ET:** yedek alıp en az bir kez geri-yükleme denemesi yapılmadıysa "yedek yok"
  demektir. Prosedürü buraya yaz.

## 2. Migration disiplini (KRİTİK)
`supabase/schema.sql` tek-dosya kurulum scriptidir; **yıkıcı DROP** içerir. Artık başında bir
**GUARD** var: `conversations`/`messages` boş değilse script **durur** (kazara prod re-run = veri
kaybını önler). Yine de:
- **Artımlı değişiklik** için bu dosyayı düzenleyip yeniden çalıştırma. Versiyonlu migration kullan:
  `supabase/migrations/NNNN_aciklama.sql` + `supabase db push` (Supabase CLI).
- Tablo şeması değişince: yeni migration dosyası yaz (ALTER), `schema.sql`'i de güncel tut
  (yeni temiz kurulum için kaynak-doğru kalsın).

## 3. Hesap silme (GDPR/KVKK-eşdeğeri) — BACKLOG
Şu an `deleteAllConversationsSb` (veri siler) + `clearPrefsSb` (tercih sıfırlar) var ama **tam
hesap silme yok**. `auth.users` yalnız **service_role** ile silinir (client anon ile silemez).
`profiles_delete_own` RLS policy'si mevcut ama UI çağırmıyor (şimdilik ölü).
- **Yap (lansmandan önce):** bir **Edge Function** (service_role): kullanıcı JWT'sini doğrula →
  `auth.admin.deleteUser(uid)`. `auth.users` silinince profiles/conversations/messages/
  uploaded_files **ON DELETE CASCADE** ile gider (zincir doğrulandı). UI'da UserMenu'ye
  "Hesabımı kalıcı sil" + onay modalı ekle.

## 4. Eşzamanlılık limiti (BİLİNEN — düşük risk)
`save_conversation` atomik (tek transaction). Ancak aynı kullanıcı **aynı sohbeti 2 sekmede**
aynı anda kaydederse **last-writer-wins**: ikinci kayıt birincinin mesajlarını ezer. Tek
kullanıcılı kullanımda nadir; veri **bozulmaz/sızmaz**, yalnız son yazan kazanır.
- **İleride (gerekirse):** `conversations.version` (optimistic lock) + RPC `p_version` + frontend
  stale-version retry/merge. Şimdilik backlog (mevcut ölçek için YAGNI).

## 5. Gözlemlenebilirlik — BACKLOG
`logSync` şu an yalnız `console.warn` (kullanıcı konsolu; takım görmüyor). Sessiz senkron
hataları üretimde fark edilmez.
- **Yap:** `logSync`'i Sentry / Supabase **Log Drains** / Logflare'e bağla (en azından RPC error
  oranı). Supabase Dashboard → **Reports** ile RLS-reddi + p95 sorgu süresini periyodik izle.
- Gerçek veriyle bir kez `EXPLAIN` çalıştır: `loadConversationsSb` nested select planını doğrula.

## 6. Rate limiting / abuse — BACKLOG (düşük öncelik)
`upsertConversationSb` her tamamlanan turda çağrılır (zaten seyrek). Buggy/kötü niyetli client
spam'lerse `save_conversation` yükü artar. `MAX_CONVERSATIONS=100` satır sayısını sınırlar ama
çağrı sıklığını değil.
- **İleride:** frontend debounce (tur başına ≤1 çağrı/N sn) + Supabase API Gateway rate-limit
  ayarlarını lansmanda gözden geçir.

## 7. E-posta doğrulama gate'i (PROD POSTÜRÜ)
RLS policy'leri `auth.uid()` kullanır — **doğrulanmış e-posta** ŞART KOŞMAZ. Yani Supabase'de
"Confirm email" KAPALIYSA doğrulanmamış hesaplar RLS'i geçer.
- **Prod:** Supabase → Authentication → Email → **"Confirm email" AÇIK tut** (önerilen).
- **Daha sıkı (opsiyonel):** RLS policy'lere `(select auth.jwt()->>'email_confirmed_at') is not null`
  ekle. DİKKAT: bunu eklersen "Confirm email" KAPALI iken HİÇ KİMSE giremez (kilitlenme). Bu yüzden
  varsayılanda eklemedik; prod'da Confirm-AÇIK + (istenirse) bu gate birlikte kullanılmalı.

## 8. Backend bağlantı havuzu (PHASE C notu)
Şu an backend Postgres'e bağlanmıyor (frontend doğrudan supabase-js + RLS). Phase C'de FastAPI
doğrudan bağlanırsa:
- **TRANSACTION-mode pooler** (port 6543) kullan; prepared statement'ları desteklemez →
  asyncpg `statement_cache_size=0` / SQLAlchemy `prepared_statement_cache_size=0` (`?pgbouncer=true`).
- Migration/DDL için **direct connection**, runtime için **pooler** ayrımını koru.
- Direct connection (5432) IPv4'te artık eklenti/ücretli → pooler tercih et.

## 9. Ölçek: lazy-load (BACKLOG — büyüyünce)
`loadConversationsSb` ilk yüklemede tüm sohbet + tüm mesaj içeriğini tek sorguda çeker. Güç
kullanıcıda (100 sohbet × büyük dilekçe metinleri) payload büyür. Mevcut ölçek için sorun değil
(MAX_CONVERSATIONS=100 + tipik mesaj boyutu). Büyüyünce: metadata-önce + sohbet açılınca mesaj-sonra
(iki adımlı lazy-load). Not: bu, yerel arama/Kaynaklar/Dosyalarım toplama mantığını etkiler.

## 10. Veri saklama (retention) — POLİTİKA KARARI
DB'de sohbet/mesaj sınırsız büyür (client 100 gösterse de eskiler DB'de kalır). Karar ver +
belgele: "süresiz sakla" (hukuki kayıt) **veya** "N gün sonra arşivle/sil". Şu an süresiz.
