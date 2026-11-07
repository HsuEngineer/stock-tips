#!/bin/bash
# Stock Tips — idempotent full install for Ubuntu / GCP Compute Engine.
#
# Usage (on the VM, from repo root or anywhere):
#   sudo ./deploy/install.sh
#   sudo DISCORD_TOKEN=... DISCORD_CHANNEL_ID=... DISCORD_OWNER_IDS=... ./deploy/install.sh
#   sudo ./deploy/install.sh --secrets /path/to/secrets.env
#
# What it does:
#   1) apt: python3, venv, pip, git, mysql-server
#   2) MySQL DB + dedicated app user (random password if unset)
#   3) Clone/update repo into INSTALL_DIR
#   4) venv + pip install
#   5) Write config.ini from secrets / env
#   6) systemd unit + enable/start
#   7) passwordless sudo for reboot + systemctl restart
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_FROM_SCRIPT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --------------- defaults ---------------
GIT_REPO="${GIT_REPO:-https://github.com/HsuEngineer/stock-tips.git}"
GIT_BRANCH="${GIT_BRANCH:-master}"
INSTALL_DIR="${INSTALL_DIR:-/opt/stock-tips}"
SERVICE_USER="${SERVICE_USER:-}"
DB_NAME="${DB_NAME:-Stock}"
DB_USER="${DB_USER:-stocktips}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
APP_LANGUAGE="${APP_LANGUAGE:-zh-TW}"
POLL_INTERVAL_MINUTES="${POLL_INTERVAL_MINUTES:-10}"
SHARP_MOVE_PCT="${SHARP_MOVE_PCT:-2.0}"
CONSTITUENT_REFRESH_MONTHS="${CONSTITUENT_REFRESH_MONTHS:-3,6,9,12}"
ETF_FUND_ID="${ETF_FUND_ID:-1066}"
DISCORD_TOKEN="${DISCORD_TOKEN:-}"
DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-}"
DISCORD_OWNER_IDS="${DISCORD_OWNER_IDS:-}"
SECRETS_FILE=""
SKIP_START=0
START_ONLY=0

log()  { echo "[stocktips] $*"; }
die()  { echo "[stocktips] ERROR: $*" >&2; exit 1; }
need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Run as root: sudo $0 $*"
  fi
}

usage() {
  cat <<'EOF'
Usage: sudo ./deploy/install.sh [options]

Options:
  --secrets PATH     Load DISCORD_* / DB_* from env file
  --install-dir DIR  Default: /opt/stock-tips
  --user NAME        Service user (default: SUDO_USER or ubuntu)
  --repo URL         Git clone URL
  --branch NAME      Git branch (default: master)
  --skip-start       Install everything but do not start the unit
  --start-only       Only (re)write systemd + start (repo already present)
  -h, --help         Show help

Env / secrets file keys:
  DISCORD_TOKEN  DISCORD_CHANNEL_ID  DISCORD_OWNER_IDS
  DB_PASSWORD (optional; auto-generated if empty)
  APP_LANGUAGE  POLL_INTERVAL_MINUTES  SHARP_MOVE_PCT
EOF
}

load_secrets_file() {
  local f="$1"
  [[ -f "$f" ]] || die "Secrets file not found: $f"
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --secrets) SECRETS_FILE="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --user) SERVICE_USER="$2"; shift 2 ;;
    --repo) GIT_REPO="$2"; shift 2 ;;
    --branch) GIT_BRANCH="$2"; shift 2 ;;
    --skip-start) SKIP_START=1; shift ;;
    --start-only) START_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

need_root "$@"

if [[ -n "${SECRETS_FILE}" ]]; then
  load_secrets_file "${SECRETS_FILE}"
elif [[ -f "${SCRIPT_DIR}/secrets.env" ]]; then
  log "Loading ${SCRIPT_DIR}/secrets.env"
  load_secrets_file "${SCRIPT_DIR}/secrets.env"
fi

# Re-read after secrets (file may set them)
DISCORD_TOKEN="${DISCORD_TOKEN:-}"
DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-}"
DISCORD_OWNER_IDS="${DISCORD_OWNER_IDS:-}"
DB_PASSWORD="${DB_PASSWORD:-}"

if [[ -z "${SERVICE_USER}" ]]; then
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    SERVICE_USER="${SUDO_USER}"
  elif id ubuntu &>/dev/null; then
    SERVICE_USER="ubuntu"
  else
    SERVICE_USER="root"
  fi
fi

id "${SERVICE_USER}" &>/dev/null || die "User '${SERVICE_USER}' does not exist"

rand_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24 | tr -d '/+=' | head -c 24
  else
    head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24
  fi
}

set_ini_key() {
  # set_ini_key FILE SECTION KEY VALUE
  local file="$1" section="$2" key="$3" value="$4"
  python3 - "$file" "$section" "$key" "$value" <<'PY'
import configparser, sys
path, section, key, value = sys.argv[1:5]
cfg = configparser.ConfigParser()
cfg.read(path, encoding="utf-8")
if section not in cfg:
    cfg[section] = {}
cfg[section][key] = value
with open(path, "w", encoding="utf-8") as f:
    cfg.write(f)
PY
}

install_packages() {
  log "Installing OS packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    git curl ca-certificates openssl \
    mysql-server
}

ensure_mysql() {
  log "Starting MySQL..."
  systemctl enable mysql 2>/dev/null || systemctl enable mysqld 2>/dev/null || true
  systemctl start mysql 2>/dev/null || systemctl start mysqld 2>/dev/null || true
  # Wait until mysql accepts connections via sudo
  for i in $(seq 1 30); do
    if sudo mysql -e "SELECT 1" &>/dev/null; then
      break
    fi
    sleep 1
  done
  sudo mysql -e "SELECT 1" &>/dev/null || die "MySQL did not become ready"

  if [[ -z "${DB_PASSWORD}" ]]; then
    if [[ -f "${INSTALL_DIR}/config.ini" ]]; then
      # Reuse existing password on re-install
      DB_PASSWORD="$(python3 - <<PY
import configparser
c=configparser.ConfigParser()
c.read("${INSTALL_DIR}/config.ini", encoding="utf-8")
print(c.get("DATABASE","PASSWORD", fallback=""))
PY
)"
    fi
  fi
  if [[ -z "${DB_PASSWORD}" ]]; then
    DB_PASSWORD="$(rand_password)"
    log "Generated DB password for user '${DB_USER}' (saved into config.ini)"
  fi

  log "Creating database '${DB_NAME}' and user '${DB_USER}'..."
  # Escape single quotes for SQL
  local pw_sql="${DB_PASSWORD//\'/\\\'}"
  sudo mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${pw_sql}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${pw_sql}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
}

preserve_config() {
  local cfg_backup=""
  if [[ -f "${INSTALL_DIR}/config.ini" ]]; then
    cfg_backup="$(mktemp)"
    cp -a "${INSTALL_DIR}/config.ini" "${cfg_backup}"
  fi
  echo "${cfg_backup}"
}

restore_config() {
  local cfg_backup="$1"
  if [[ -n "${cfg_backup}" && -f "${cfg_backup}" ]]; then
    cp -a "${cfg_backup}" "${INSTALL_DIR}/config.ini"
    rm -f "${cfg_backup}"
  fi
}

git_reset_install_dir() {
  local cfg_backup
  cfg_backup="$(preserve_config)"
  git -C "${INSTALL_DIR}" fetch origin
  git -C "${INSTALL_DIR}" checkout "${GIT_BRANCH}"
  git -C "${INSTALL_DIR}" reset --hard "origin/${GIT_BRANCH}"
  restore_config "${cfg_backup}"
}

sync_repo() {
  log "Syncing code into ${INSTALL_DIR} ..."
  mkdir -p "$(dirname "${INSTALL_DIR}")"

  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    git_reset_install_dir
  elif [[ -f "${INSTALL_DIR}/main.py" ]]; then
    # Already unpacked at INSTALL_DIR (e.g. ran install from /opt/stock-tips)
    log "Found existing tree at ${INSTALL_DIR}; leaving files in place."
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
      git -C "${INSTALL_DIR}" init
      git -C "${INSTALL_DIR}" remote add origin "${GIT_REPO}" 2>/dev/null || \
        git -C "${INSTALL_DIR}" remote set-url origin "${GIT_REPO}"
      # Best-effort: fetch so later /update works
      git -C "${INSTALL_DIR}" fetch origin 2>/dev/null || true
    fi
  elif [[ -f "${REPO_FROM_SCRIPT}/main.py" && "${REPO_FROM_SCRIPT}" != "${INSTALL_DIR}" ]]; then
    # Installing from a local checkout: copy once
    mkdir -p "${INSTALL_DIR}"
    rsync -a \
      --exclude '.venv' \
      --exclude '__pycache__' \
      --exclude 'config.ini' \
      --exclude 'deploy/secrets.env' \
      "${REPO_FROM_SCRIPT}/" "${INSTALL_DIR}/"
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
      if [[ -d "${REPO_FROM_SCRIPT}/.git" ]]; then
        # Keep git history/remote so Discord /update works
        rsync -a "${REPO_FROM_SCRIPT}/.git/" "${INSTALL_DIR}/.git/"
      else
        git -C "${INSTALL_DIR}" init
        git -C "${INSTALL_DIR}" remote add origin "${GIT_REPO}" 2>/dev/null || true
      fi
    fi
  else
    git clone --branch "${GIT_BRANCH}" "${GIT_REPO}" "${INSTALL_DIR}"
  fi

  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
}

setup_venv() {
  log "Creating virtualenv and installing Python deps..."
  local py
  py="$(command -v python3)"
  sudo -u "${SERVICE_USER}" "${py}" -m venv "${INSTALL_DIR}/.venv"
  sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -U pip
  sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
}

write_config() {
  log "Writing config.ini ..."
  local cfg="${INSTALL_DIR}/config.ini"
  if [[ ! -f "${cfg}" ]]; then
    cp "${INSTALL_DIR}/config.ini.example" "${cfg}"
  fi

  set_ini_key "${cfg}" DATABASE HOST "${DB_HOST}"
  set_ini_key "${cfg}" DATABASE PORT "${DB_PORT}"
  set_ini_key "${cfg}" DATABASE USER "${DB_USER}"
  set_ini_key "${cfg}" DATABASE PASSWORD "${DB_PASSWORD}"
  set_ini_key "${cfg}" DATABASE DATABASE "${DB_NAME}"

  if [[ -n "${DISCORD_TOKEN}" ]]; then
    set_ini_key "${cfg}" DISCORD TOKEN "${DISCORD_TOKEN}"
  fi
  if [[ -n "${DISCORD_CHANNEL_ID}" ]]; then
    set_ini_key "${cfg}" DISCORD CHANNEL_ID "${DISCORD_CHANNEL_ID}"
  fi
  if [[ -n "${DISCORD_OWNER_IDS}" ]]; then
    set_ini_key "${cfg}" DISCORD OWNER_IDS "${DISCORD_OWNER_IDS}"
  fi

  set_ini_key "${cfg}" STOCK POLL_INTERVAL_MINUTES "${POLL_INTERVAL_MINUTES}"
  set_ini_key "${cfg}" STOCK SHARP_MOVE_PCT "${SHARP_MOVE_PCT}"
  set_ini_key "${cfg}" STOCK CONSTITUENT_REFRESH_MONTHS "${CONSTITUENT_REFRESH_MONTHS}"
  set_ini_key "${cfg}" STOCK ETF_FUND_ID "${ETF_FUND_ID}"
  set_ini_key "${cfg}" APP LANGUAGE "${APP_LANGUAGE}"

  chown "${SERVICE_USER}:${SERVICE_USER}" "${cfg}"
  chmod 600 "${cfg}"

  # Validate token presence
  local token
  token="$(python3 - <<PY
import configparser
c=configparser.ConfigParser()
c.read("${cfg}", encoding="utf-8")
print(c.get("DISCORD","TOKEN", fallback=""))
PY
)"
  if [[ -z "${token}" || "${token}" == "your_bot_token" ]]; then
    log "WARNING: DISCORD.TOKEN not set. Edit ${cfg} then: sudo systemctl restart stocktips"
  fi
}

test_db() {
  log "Testing DB connection as ${DB_USER}..."
  sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/python" - <<PY
import configparser
import pymysql
c = configparser.ConfigParser()
c.read("${INSTALL_DIR}/config.ini", encoding="utf-8")
db = {k.lower(): v for k, v in c["DATABASE"].items()}
conn = pymysql.connect(
    host=db["host"],
    port=int(db["port"]),
    user=db["user"],
    password=db["password"],
    database=db["database"],
    charset="utf8mb4",
)
conn.close()
print("MySQL OK:", db["database"], "@", db["host"])
PY
}

install_sudoers() {
  log "Installing sudoers for reboot + systemctl..."
  local src="${INSTALL_DIR}/deploy/sudoers-stocktips.example"
  local dst="/etc/sudoers.d/stocktips"
  sed "s/__SERVICE_USER__/${SERVICE_USER}/g" "${src}" > "${dst}"
  chmod 440 "${dst}"
  visudo -cf "${dst}" || { rm -f "${dst}"; die "sudoers validation failed"; }
}

install_systemd() {
  log "Installing systemd unit stocktips.service ..."
  local src="${INSTALL_DIR}/deploy/stocktips.service"
  local dst="/etc/systemd/system/stocktips.service"
  sed \
    -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    "${src}" > "${dst}"
  systemctl daemon-reload
  systemctl enable stocktips.service
  if [[ "${SKIP_START}" -eq 0 ]]; then
    systemctl restart stocktips.service
    sleep 2
    systemctl --no-pager --full status stocktips.service || true
  else
    log "Skip start (--skip-start). Later: sudo systemctl start stocktips"
  fi
}

print_summary() {
  cat <<EOF

========================================
 Stock Tips install complete
========================================
 Install dir : ${INSTALL_DIR}
 Service user: ${SERVICE_USER}
 DB          : ${DB_USER}@localhost / ${DB_NAME}
 Unit        : stocktips.service

 Useful commands:
   sudo systemctl status stocktips
   sudo journalctl -u stocktips -f
   sudo systemctl restart stocktips
   nano ${INSTALL_DIR}/config.ini

 Discord: /help  /digest  /update  /restart  /reboot
========================================
EOF
}

# --------------- main ---------------
if [[ "${START_ONLY}" -eq 1 ]]; then
  [[ -f "${INSTALL_DIR}/main.py" ]] || die "No install at ${INSTALL_DIR}; run full install first"
  install_sudoers
  install_systemd
  print_summary
  exit 0
fi

install_packages
# rsync may be missing on minimal images
if ! command -v rsync >/dev/null 2>&1; then
  apt-get install -y rsync
fi
ensure_mysql
sync_repo
setup_venv
write_config
test_db
install_sudoers
install_systemd
print_summary
