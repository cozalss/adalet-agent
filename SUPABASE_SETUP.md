# Supabase Kurulumu (auth + sohbet geçmişi)

> ADALET'in giriş/kayıt + sohbet geçmişi artık **Supabase** ile çalışır.
> AI çekirdeği (FastAPI + LangGraph + yerel LLM + Qdrant) kendi sunucunda kalır;
> Supabase yalnız **auth + ilişkisel veriyi** (kullanıcı, sohbet, mesaj, tercih)
> üstlenir. Bu dosyadaki 5 adımı bir kez yap → kod canlı çalışır.

## 1. Proje oluştur (2 dk)
1. https://supabase.com → giriş → **New project**
2. İsim: `adalet`, güçlü bir DB şifresi belirle, bölge: **Frankfurt (eu-central-1)** (TR'ye en yakın)
3. Proje hazır olunca **Settings → API**'den şunları kopyala:
   - **Project URL** → `VITE_SUPABASE_URL`
   - **anon public** key → `VITE_SUPABASE_ANON_KEY`
   - **JWT Secret** (Settings → API → JWT Settings) → backend için `SUPABASE_JWT_SECRET`

## 2. Şemayı kur
**SQL Editor** → New query → `supabase/schema.sql` dosyasının tamamını yapıştır → **RUN**.
(profiles + conversations + messages + uploaded_files tabloları + RLS politikaları +
yeni-kullanıcı trigger'ı oluşur. RLS sayesinde her kullanıcı yalnız kendi verisini görür.)

> 2026-05-30 sonrası yeni Supabase projelerinde `public` tablolar Data API'ye
> otomatik açılmaz. `schema.sql` bu yüzden `authenticated` role için explicit
> `GRANT` satırlarını içerir; `anon` role custom tablo yetkisi verilmez. Mevcut
> projeyi artımlı güncelliyorsan `supabase/migrations/0002_explicit_data_api_grants.sql`
> dosyasını da SQL Editor'de çalıştır.

## 3. Auth sağlayıcılarını aç
> **Misafir modu YOK:** siteye yalnız kayıt olup giriş yapan kullanıcı girebilir.
> Giriş yoksa `AuthPage` gösterilir (uygulama açılmaz).

**Authentication → Providers**:
- **Email**: açık (varsayılan).
  - **Confirm email AÇIK** (önerilen, prod): kayıt sonrası kullanıcı e-postasındaki
    onay linkine tıklar; sonra giriş yapar. Uygulama bunu yönetir — kayıt sonrası
    "e-postanı doğrula" bildirimi gösterir + giriş sekmesine geçer (boşta kalmaz).
  - **Confirm email KAPALI** (yalnız hızlı demo): kayıt anında giriş olur. DİKKAT:
    doğrulanmamış e-postalar oturum açabilir — prod'da AÇIK tut.
- **Google** (opsiyonel, demo cilası): Google Cloud'da OAuth client oluştur →
  Client ID/Secret'i buraya gir. (Email/şifre bunsuz da çalışır.)

**Authentication → Security**:
- **Leaked Password Protection**: Pro plan ve üstünde AÇIK tut. Supabase advisor
  `auth_leaked_password_protection` uyarısı veriyorsa bu toggle kapalıdır.
  ADALET web signup tarafında ayrıca `VITE_HIBP_PASSWORD_CHECK=1` ile HIBP
  Pwned Passwords k-anonymity range check çalışır; şifrenin kendisi veya tam
  hash'i gönderilmez. Eski internal auth yolu da `password_policy_issues`
  fallback'iyle yaygın kalıpları, düşük karmaşıklığı ve e-posta/ad içeren
  parolaları reddeder.

**Authentication → URL Configuration**: Site URL'e dev için `http://localhost:5173`,
prod için Vercel domain'ini ekle (şifre-sıfırlama/confirm linkleri buraya döner).

## 4. Frontend env
```bash
cd frontend
cp .env.example .env
# .env içine VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY yapıştır
```

## 5. Backend env (FastAPI /ask Supabase JWT'sini doğrular)
Backend `.env`'e ekle:
```
AUTH_ENABLED=1
AUTH_PROVIDER=supabase
SUPABASE_JWT_SECRET=<adım 1'deki JWT Secret>
```
> FastAPI artık kendi /auth/login'ini değil, Supabase'in verdiği JWT'yi doğrular
> (kullanıcıyı `sub`=UUID ile tanır). Sohbet/mesaj CRUD'u frontend doğrudan
> Supabase'e yapar (supabase-js + RLS).

---

### Sürüm notu
- **Env ayarlı değilse** uygulama çökmez ama **giriş kullanılamaz** (misafir modu
  yok): AuthPage "Giriş servisi yapılandırılmadı" uyarısı gösterir, butonlar pasif.
  Deploy'da `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` ZORUNLU.
- Eski custom auth (`/auth/register`, `/auth/login`, `UserAccount`, `passwords.py`)
  ve `/me/*` uçları Supabase geçişiyle **emekliye ayrılır** (ayrı commit'te temizlenir).
- Ücretsiz katman: proje ~1 hafta atıl kalırsa duraklatılır — demo öncesi Dashboard'dan uyandır.
