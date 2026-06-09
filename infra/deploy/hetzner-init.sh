#!/usr/bin/env bash
# ADALET-AGENT — Hetzner staging init script (Sprint-4 W9.2)
#
# Çıplak Ubuntu 24.04 sunucudan, deploy-edilebilir staging'e:
#   1. Sistem güncelleme + temel paketler
#   2. Docker + Docker Compose
#   3. NVIDIA Container Toolkit (RTX 4070 GPU passthrough için)
#   4. Firewall (UFW) — sadece 22/80/443
#   5. Fail2ban + unattended-upgrades
#   6. Repo clone + .env oluştur (placeholder)
#
# Kullanım:
#   ssh root@<server-ip>
#   bash <(curl -fsSL https://raw.githubusercontent.com/<org>/adalet-agent/main/infra/deploy/hetzner-init.sh)
#
# SONRAKİ ADIM: .env'i secret'lar ile doldur, `docker compose up -d`

set -euo pipefail

readonly REPO_URL="${REPO_URL:-https://github.com/REPLACE-WITH-ORG/adalet-agent.git}"
readonly DEPLOY_DIR="/opt/adalet-agent"
readonly DEPLOY_USER="adalet"

log() { printf '\033[1;32m[init]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# --- root check ---
[[ $EUID -eq 0 ]] || fail "root olarak çalıştır (sudo bash $0)"

# --- 1. sistem update ---
log "apt update + upgrade"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
	ca-certificates curl gnupg lsb-release \
	ufw fail2ban unattended-upgrades \
	htop git jq tmux

# --- 2. Docker ---
if ! command -v docker &>/dev/null; then
	log "Docker kurulumu"
	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
	chmod a+r /etc/apt/keyrings/docker.gpg
	echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" >/etc/apt/sources.list.d/docker.list
	apt-get update -qq
	apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
	systemctl enable --now docker
fi
log "Docker $(docker --version)"

# --- 3. NVIDIA Container Toolkit (eğer GPU varsa) ---
if lspci | grep -i nvidia &>/dev/null; then
	log "NVIDIA GPU bulundu, Container Toolkit kurulumu"
	curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
	curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' >/etc/apt/sources.list.d/nvidia-container-toolkit.list
	apt-get update -qq
	apt-get install -y -qq nvidia-container-toolkit
	nvidia-ctk runtime configure --runtime=docker
	systemctl restart docker
fi

# --- 4. Firewall ---
log "UFW konfigürasyonu"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP/ACME"
ufw allow 443/tcp comment "HTTPS"
ufw --force enable

# --- 5. Fail2ban + unattended-upgrades ---
log "fail2ban + unattended-upgrades"
systemctl enable --now fail2ban
dpkg-reconfigure -plow unattended-upgrades || true

# --- 6. Deploy user + repo ---
if ! id "$DEPLOY_USER" &>/dev/null; then
	log "deploy kullanıcısı oluştur: $DEPLOY_USER"
	useradd -m -s /bin/bash -G docker "$DEPLOY_USER"
fi

mkdir -p "$DEPLOY_DIR"
chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$DEPLOY_DIR"

if [[ ! -d "$DEPLOY_DIR/.git" ]]; then
	log "repo clone: $REPO_URL"
	sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$DEPLOY_DIR"
else
	log "repo update"
	sudo -u "$DEPLOY_USER" git -C "$DEPLOY_DIR" pull --ff-only
fi

# --- 7. .env template ---
if [[ ! -f "$DEPLOY_DIR/.env" ]]; then
	log ".env template oluşturuluyor"
	cat >"$DEPLOY_DIR/.env" <<EOF
# Production secrets — placeholder, DOLDUR
REDIS_PASSWORD=$(openssl rand -base64 48 | tr -d '\n+/=')
QDRANT_API_KEY=$(openssl rand -base64 64 | tr -d '\n+/=')
JWT_SECRET=$(openssl rand -hex 32)
AUTH_ENABLED=1
JWT_ISSUER=adalet-agent
JWT_AUDIENCE=adalet-agent-api
JWT_TTL_SECONDS=86400

# Sanitize / PII
SANITIZE_ENABLED=1
PII_ENABLED=1

# LLM (W9.3 sonrası llama-server entegre)
LLM_MODE=llamacpp_server
LLM_SERVER_URL=http://llama-server:8080

# Retrieval feature toggles
HYDE_ENABLED=1
MULTI_QUERY_ENABLED=1
COLBERT_QUERY_ENABLED=1
MEVZUAT_DOMAIN_FILTER=1
RAPTOR_ENABLED=1
GRAPH_RAG_ENABLED=1

# CORS — frontend domain'lerini ekle
ALLOWED_ORIGINS=https://staging.adalet.app,https://adalet.app

# Observability (opsiyonel)
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
LOG_FORMAT=json
LOG_LEVEL=INFO
EOF
	chown "$DEPLOY_USER":"$DEPLOY_USER" "$DEPLOY_DIR/.env"
	chmod 600 "$DEPLOY_DIR/.env"
	log ".env oluşturuldu — secret rotation runbook'a göre 90 günde bir rotate et"
fi

# --- 8. Otomatik yedekleme cron'u (denetim #10 — "veri kaybı kabul edilemez") ---
# DB_OPERATIONS.md: Postgres'te otomatik yedek YOK'tu → init artık günlük pg_dump kurar.
# Postgres = KRİTİK veri (hesap/sohbet/audit); Qdrant corpus'u kamuya-açık kaynaktan
# yeniden seed edilebilir (best-effort snapshot). Cron DEPLOY_USER (docker grubunda) ile.
log "yedekleme cron'u kuruluyor (günlük pg_dump + Qdrant snapshot, 7-gün retention)"
mkdir -p /var/backups/adalet/postgres /var/backups/adalet/qdrant
chown -R "$DEPLOY_USER":"$DEPLOY_USER" /var/backups/adalet
_CRON_PG='0 3 * * * docker exec adalet-postgres pg_dump -U ${POSTGRES_USER:-adalet} ${POSTGRES_DB:-adalet} 2>/var/backups/adalet/postgres/last_err.log | gzip > /var/backups/adalet/postgres/adalet_$(date +\%F).sql.gz && find /var/backups/adalet/postgres -name "*.sql.gz" -mtime +7 -delete'
_CRON_QD='30 3 * * * docker exec adalet-backend python -m scripts.backup_qdrant --retention 7 > /var/backups/adalet/qdrant/last.log 2>&1'
# Idempotent: mevcut crontab'tan eski ADALET satırlarını çıkar, yenilerini ekle.
{ sudo -u "$DEPLOY_USER" crontab -l 2>/dev/null | grep -vE 'adalet-postgres pg_dump|scripts.backup_qdrant' || true; \
  echo "$_CRON_PG"; echo "$_CRON_QD"; } | sudo -u "$DEPLOY_USER" crontab -
log "yedek cron kuruldu — restore'u EN AZ BİR KEZ test et (DB_OPERATIONS.md §1)"

log ""
log "==============================================="
log "init başarılı. Sonraki adımlar:"
log "  1. $DEPLOY_DIR/.env'i kontrol et / düzenle"
log "  2. DNS A kaydı: staging.adalet.app → <server-ip>"
log "  3. cd $DEPLOY_DIR && docker compose --env-file .env up -d"
log "  4. Bir kez Caddy ACME sertifika alacak (~30s)"
log "  5. curl https://staging.adalet.app/health"
log "==============================================="
