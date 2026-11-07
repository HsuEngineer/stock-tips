#!/bin/bash
# Create a GCP Compute Engine VM and auto-install Stock Tips on first boot.
#
# Prerequisites (on your laptop / Cloud Shell):
#   - gcloud CLI authenticated: gcloud auth login && gcloud config set project PROJECT_ID
#   - APIs: compute.googleapis.com
#
# Usage:
#   cp deploy/secrets.env.example deploy/secrets.env   # fill Discord values
#   ./deploy/gcp-create-vm.sh
#   ./deploy/gcp-create-vm.sh --project my-proj --zone asia-east1-b --name stock-tips
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${ZONE:-asia-east1-b}"
NAME="${NAME:-stock-tips}"
MACHINE="${MACHINE:-e2-small}"
IMAGE_FAMILY="${IMAGE_FAMILY:-ubuntu-2204-lts}"
IMAGE_PROJECT="${IMAGE_PROJECT:-ubuntu-os-cloud}"
DISK_SIZE="${DISK_SIZE:-20}"
GIT_REPO="${GIT_REPO:-https://github.com/HsuEngineer/stock-tips.git}"
GIT_BRANCH="${GIT_BRANCH:-master}"
INSTALL_DIR="${INSTALL_DIR:-/opt/stock-tips}"
SECRETS_FILE="${SECRETS_FILE:-${SCRIPT_DIR}/secrets.env}"
STARTUP_LOCAL="${SCRIPT_DIR}/gcp-startup.sh"
TAGS="${TAGS:-stocktips}"

DISCORD_TOKEN="${DISCORD_TOKEN:-}"
DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-}"
DISCORD_OWNER_IDS="${DISCORD_OWNER_IDS:-}"

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[gcp-create-vm] $*"; }

usage() {
  cat <<'EOF'
Usage: ./deploy/gcp-create-vm.sh [options]

Options:
  --project ID       GCP project (default: gcloud config)
  --zone ZONE        Default: asia-east1-b
  --name NAME        VM name (default: stock-tips)
  --machine TYPE     Default: e2-small
  --secrets PATH     Env file with DISCORD_* (default: deploy/secrets.env)
  --repo URL         Git repo to install on the VM
  --branch NAME      Git branch
  --disk-size GB     Boot disk size (default: 20)
  -h, --help

After create, watch first-boot install:
  gcloud compute ssh NAME --zone ZONE --command 'sudo tail -f /var/log/stocktips-startup.log'
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --zone) ZONE="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --machine) MACHINE="$2"; shift 2 ;;
    --secrets) SECRETS_FILE="$2"; shift 2 ;;
    --repo) GIT_REPO="$2"; shift 2 ;;
    --branch) GIT_BRANCH="$2"; shift 2 ;;
    --disk-size) DISK_SIZE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

command -v gcloud >/dev/null 2>&1 || die "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
[[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]] || die "Set project: gcloud config set project PROJECT_ID  or  --project"
[[ -f "${STARTUP_LOCAL}" ]] || die "Missing ${STARTUP_LOCAL}"

if [[ -f "${SECRETS_FILE}" ]]; then
  log "Loading secrets from ${SECRETS_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${SECRETS_FILE}"
  set +a
fi

DISCORD_TOKEN="${DISCORD_TOKEN:-}"
DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-}"
DISCORD_OWNER_IDS="${DISCORD_OWNER_IDS:-}"

[[ -n "${DISCORD_TOKEN}" && "${DISCORD_TOKEN}" != "your_bot_token" ]] \
  || die "Set DISCORD_TOKEN in ${SECRETS_FILE} or the environment"
[[ -n "${DISCORD_CHANNEL_ID}" && "${DISCORD_CHANNEL_ID}" != "1234567890" ]] \
  || die "Set DISCORD_CHANNEL_ID in ${SECRETS_FILE}"
[[ -n "${DISCORD_OWNER_IDS}" ]] \
  || die "Set DISCORD_OWNER_IDS in ${SECRETS_FILE}"

log "Enabling Compute Engine API (idempotent)..."
gcloud services enable compute.googleapis.com --project="${PROJECT}"

# Network: Discord bot only needs egress; no inbound firewall rule required.
log "Creating VM ${NAME} in ${ZONE} (${MACHINE})..."
gcloud compute instances create "${NAME}" \
  --project="${PROJECT}" \
  --zone="${ZONE}" \
  --machine-type="${MACHINE}" \
  --image-family="${IMAGE_FAMILY}" \
  --image-project="${IMAGE_PROJECT}" \
  --boot-disk-size="${DISK_SIZE}GB" \
  --boot-disk-type=pd-balanced \
  --tags="${TAGS}" \
  --scopes=https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write \
  --metadata-from-file=startup-script="${STARTUP_LOCAL}" \
  --metadata=stocktips-discord-token="${DISCORD_TOKEN}",stocktips-channel-id="${DISCORD_CHANNEL_ID}",stocktips-owner-ids="${DISCORD_OWNER_IDS}",stocktips-repo="${GIT_REPO}",stocktips-branch="${GIT_BRANCH}",stocktips-install-dir="${INSTALL_DIR}"

EXTERNAL_IP="$(gcloud compute instances describe "${NAME}" \
  --project="${PROJECT}" \
  --zone="${ZONE}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

cat <<EOF

========================================
 VM created — first-boot install running
========================================
 Project : ${PROJECT}
 Name    : ${NAME}
 Zone    : ${ZONE}
 IP      : ${EXTERNAL_IP}

Watch install (2–5 minutes typical):
  gcloud compute ssh ${NAME} --project=${PROJECT} --zone=${ZONE} --command 'sudo tail -f /var/log/stocktips-startup.log'

Check bot service:
  gcloud compute ssh ${NAME} --project=${PROJECT} --zone=${ZONE} --command 'sudo systemctl status stocktips'

SSH:
  gcloud compute ssh ${NAME} --project=${PROJECT} --zone=${ZONE}

Security note:
  Discord token was stored in instance metadata for first boot.
  After the bot is healthy, clear it:
    gcloud compute instances remove-metadata ${NAME} --project=${PROJECT} --zone=${ZONE} \\
      --keys=stocktips-discord-token,stocktips-channel-id,stocktips-owner-ids
  (config.ini on the VM already has the values.)
========================================
EOF
