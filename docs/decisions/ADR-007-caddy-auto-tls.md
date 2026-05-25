# ADR-007 — Caddy 2 auto-TLS (Nginx + Certbot yerine)

**Durum:** Accepted
**Tarih:** 2026-05-24
**Sprint:** 4 / W9.1

## Bağlam
Production staging için reverse-proxy + TLS gerek. Sektörel default Nginx +
Certbot acme.sh. Alternatif Caddy 2, Traefik, AWS ALB.

Hetzner CCX23 (cloud VM, ALB yok), 1-kişilik backend ekibi:
- Acme yönetimi otomatik olsun (60 günde sertifika yenileme stress'i yok)
- Config dosyası okunabilir olsun (Nginx config debug zor)
- Security header'lar tek yerde toplu olsun
- SSE stream desteği (Nginx default'ta buffer açar)

## Karar
**Caddy 2** reverse-proxy + auto-TLS.

`infra/Caddyfile`:
- ACME auto: domain validate + 90-günlük cert + auto-renew (60g öncesinden)
- TLS 1.2 + 1.3, h1/h2/h3
- Security headers tek `header` blok:
  - HSTS 1 yıl preload-eligible
  - X-Frame-Options DENY, X-Content-Type-Options nosniff
  - Referrer-Policy strict-origin-when-cross-origin
  - Permissions-Policy
  - CSP minimal (backend-only)
- `flush_interval -1` SSE stream için Caddy buffer'ı kapat
- Access log JSON rotation (100MB × 14 dosya)

## Sonuç
- 80 satırlık Caddyfile = Nginx config + Certbot crontab + headers
- Sertifika yenileme operasyonel sıfır
- Production deploy'da `docker compose up -d caddy` → tek komutta TLS+proxy
- Sprint-4 production maliyet: Caddy + 1× Hetzner CCX23 = ~€15/ay

## Alternatifler
- **Nginx + Certbot**: 3 config dosyası, manuel renewal sorunu (cron'da fail
  olduğunda alert yok). Reddedildi.
- **Traefik**: Docker label-based auto-discovery güzel ama config syntax
  daha karmaşık.
- **Cloudflare proxy**: ücretsiz, DDoS koruma + TLS termination dahil. Ek
  layer; Caddy ile combine edilebilir (W10 sonrası eklenir).

## İlgili
- [infra/Caddyfile](../../adalet-agent/infra/Caddyfile)
- [docker-compose.yml](../../adalet-agent/docker-compose.yml) (placeholder section)
- docs/runbooks/deploy-staging.md
