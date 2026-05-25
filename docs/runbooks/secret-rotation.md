# Secret Rotation Runbook

> Sprint-4 W7.7 — production secret rotation prosedürü. 90 günde bir veya
> ekipten ayrılma sonrası uygulanmalıdır.

## Etkilenen Secret'lar

| Secret | Kullandığı yer | Rotation etkisi |
|---|---|---|
| `JWT_SECRET` | api/middleware/auth.py | Tüm aktif token'lar invalid (kullanıcı re-login) |
| `REDIS_PASSWORD` | docker-compose, redis, session_store | Backend restart şart |
| `QDRANT_API_KEY` | docker-compose, qdrant, vector_store | Backend restart şart |
| `API_KEYS_FILE` entries | B2B partner key'leri | Partner ile koordinasyon |
| `LANGFUSE_PUBLIC_KEY` / `_SECRET_KEY` | Observability | Trace stream ara durabilir |
| TLS sertifika (Caddy) | infra/Caddyfile | Auto-renew (Caddy ACME) |

## Tetikleyiciler

- 90 gün geçti (cron reminder)
- Ekip üyesi ayrıldı (zorunlu — same day)
- Şüpheli aktivite (audit log anomaly)
- Bilinmeyen IP'den admin login
- Bağımlılık güvenlik bülteni (CVE)

## JWT Secret Rotation

### 1. Yeni secret üret
```bash
openssl rand -hex 32 > /tmp/jwt_secret_new
# Veya: python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Yeni secret'i secrets manager'a yaz
```bash
# Hetzner için: .env güncelle, restart
# Production: AWS Secrets Manager / 1Password Connect / HashiCorp Vault
```

### 3. Backend restart
```bash
cd /opt/adalet-agent
docker compose --env-file .env restart backend
# Liveness: curl https://staging.adalet.app/health
```

### 4. Beta kullanıcılarına notify
- Slack `#adalet-beta`'ya post: "Token'ınız geçersizleşti, lütfen yeniden giriş yapın"
- Email shadow uyarı (template `docs/templates/jwt-rotation-email.txt`)

### 5. Audit doğrulama
```bash
# Eski JWT ile 401 alındığını doğrula
curl -H "Authorization: Bearer $OLD_TOKEN" https://staging.adalet.app/ask -X POST -d '{...}'
# Expect: 401 token süresi doldu / geçersiz
```

## Redis Password Rotation

### 1. Yeni password
```bash
openssl rand -base64 48
```

### 2. Coordinated restart (downtime ~30s)
```bash
cd /opt/adalet-agent
# .env'de REDIS_PASSWORD güncelle
docker compose --env-file .env up -d --force-recreate redis backend
```

### 3. Session verisi etkilenmez (Redis volume aynı), sadece auth değişir.

## Qdrant API Key Rotation

### 1. Yeni key (uzun random)
```bash
openssl rand -base64 64
```

### 2. Update env + restart
```bash
# Önce yeni key Qdrant config'e (env)
# Sonra backend QDRANT_API_KEY'i yeni değer
docker compose --env-file .env up -d --force-recreate qdrant backend
```

### 3. Veri kaybı yok (volume persistent).

## API Key (B2B) Rotation

### Per-partner rotation
```bash
# 1. Yeni key üret + label
NEW_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. API_KEYS_FILE'a ekle (eskisini hemen silme — overlap window)
jq --arg key "$NEW_KEY" --arg label "alpha-corp" \
   '. + {($key): $label}' \
   /run/secrets/api_keys.json > /tmp/keys.json
mv /tmp/keys.json /run/secrets/api_keys.json

# 3. Partner'a yeni key'i secure channel (SOPS-encrypted email)
# 4. 48h overlap window (partner uygulamasını migrate etsin)
# 5. Eski key'i sil
jq 'del(.["OLD_KEY"])' /run/secrets/api_keys.json > /tmp/keys.json
mv /tmp/keys.json /run/secrets/api_keys.json
docker compose restart backend  # cache invalidate
```

## TLS Sertifika

Caddy ACME otomatik renew yapar (60 gün öncesinden). Manuel zorla:
```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

## Rollback

Tüm rotation'larda eski değeri **48h** sakla (overlap window). Sorun olursa:
```bash
# .env'de eski değere geri al
docker compose --env-file .env up -d --force-recreate <service>
```

## Checklist Template

```
[ ] Yeni secret üretildi (uzunluk, entropy doğrulandı)
[ ] Secrets manager / .env güncellendi
[ ] Servis restart yapıldı
[ ] /health 200 dönüyor
[ ] Sample request 200 dönüyor (yeni key/secret ile)
[ ] Eski secret 48h sakla → calendar reminder
[ ] Stakeholder notify (beta users / B2B partners)
[ ] Audit log'da rotation event'i kaydedildi
```
