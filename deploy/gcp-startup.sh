#!/bin/bash
# GCP Compute Engine startup-script (runs as root on every boot).
# First boot: clone + full install. Later boots: no-op if unit already enabled
# (systemd brings the bot back by itself).
#
# Metadata keys (optional, set by gcp-create-vm.sh):
#   stocktips-discord-token
#   stocktips-channel-id
#   stocktips-owner-ids
#   stocktips-repo
#   stocktips-branch
#   stocktips-install-dir
#
set -euo pipefail

MARKER=/var/lib/stocktips-installed
INSTALL_DIR="${INSTALL_DIR:-/opt/stock-tips}"
GIT_REPO="${GIT_REPO:-https://github.com/HsuEngineer/stock-tips.git}"
GIT_BRANCH="${GIT_BRANCH:-master}"
LOG=/var/log/stocktips-startup.log

exec >>"${LOG}" 2>&1
echo "==== $(date -Is) stocktips startup ===="

meta() {
  local key="$1"
  curl -sf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" \
    || true
}

# Prefer metadata overrides when present
_m_repo="$(meta stocktips-repo)"
_m_branch="$(meta stocktips-branch)"
_m_dir="$(meta stocktips-install-dir)"
[[ -n "${_m_repo}" ]] && GIT_REPO="${_m_repo}"
[[ -n "${_m_branch}" ]] && GIT_BRANCH="${_m_branch}"
[[ -n "${_m_dir}" ]] && INSTALL_DIR="${_m_dir}"

export GIT_REPO GIT_BRANCH INSTALL_DIR
export DISCORD_TOKEN
export DISCORD_CHANNEL_ID
export DISCORD_OWNER_IDS
DISCORD_TOKEN="$(meta stocktips-discord-token)"
DISCORD_CHANNEL_ID="$(meta stocktips-channel-id)"
DISCORD_OWNER_IDS="$(meta stocktips-owner-ids)"

if [[ -f "${MARKER}" ]] && systemctl is-enabled stocktips &>/dev/null; then
  echo "Already installed; ensuring service is running..."
  systemctl start stocktips || true
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git curl ca-certificates

# Wait for network / apt lock if cloud-init still running
if command -v cloud-init >/dev/null 2>&1; then
  cloud-init status --wait || true
fi

TMP="$(mktemp -d)"
git clone --branch "${GIT_BRANCH}" "${GIT_REPO}" "${TMP}/stock-tips"
chmod +x "${TMP}/stock-tips/deploy/install.sh"

DISCORD_TOKEN="${DISCORD_TOKEN}" \
DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID}" \
DISCORD_OWNER_IDS="${DISCORD_OWNER_IDS}" \
GIT_REPO="${GIT_REPO}" \
GIT_BRANCH="${GIT_BRANCH}" \
INSTALL_DIR="${INSTALL_DIR}" \
  "${TMP}/stock-tips/deploy/install.sh"

date -Is > "${MARKER}"
echo "Install finished OK"
rm -rf "${TMP}"
