#!/bin/bash
set -euo pipefail

# Lightweight local / VM bootstrap (venv + MySQL + config.ini).
# For production on GCP with systemd auto-start, prefer:
#   sudo ./deploy/install.sh
# or from your laptop:
#   ./deploy/gcp-create-vm.sh
#
# Defaults (override via env):
#   DB_USER  DB_PASSWORD  DB_NAME

DB_USER="${DB_USER:-stocktips}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-Stock}"

rand_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24 | tr -d '/+=' | head -c 24
  else
    head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24
  fi
}

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Installing Python..."
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv openssl
  PYTHON=python3
fi

echo "Using: $PYTHON ($($PYTHON --version 2>&1))"

echo "Installing MySQL server (if needed)..."
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server openssl

echo "Starting MySQL..."
sudo systemctl enable mysql 2>/dev/null || sudo systemctl enable mysqld 2>/dev/null || true
sudo systemctl start mysql 2>/dev/null || sudo systemctl start mysqld 2>/dev/null || true

if [[ -z "${DB_PASSWORD}" ]]; then
  if [[ -f config.ini ]]; then
    DB_PASSWORD="$("$PYTHON" - <<'PY'
import configparser
c=configparser.ConfigParser()
c.read("config.ini", encoding="utf-8")
print(c.get("DATABASE","PASSWORD", fallback=""))
PY
)"
  fi
fi
if [[ -z "${DB_PASSWORD}" ]]; then
  DB_PASSWORD="$(rand_password)"
  echo "Generated DB password for '${DB_USER}' (written to config.ini)."
fi

PW_SQL="${DB_PASSWORD//\'/\\\'}"
echo "Configuring MySQL database '${DB_NAME}' and user '${DB_USER}'..."
sudo mysql <<SQL || sudo mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${PW_SQL}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${PW_SQL}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "Creating config.ini from example (keeps existing if already present)..."
if [[ ! -f config.ini ]]; then
  cp config.ini.example config.ini
fi

export STOCKTIPS_DB_USER="${DB_USER}"
export STOCKTIPS_DB_PASSWORD="${DB_PASSWORD}"
export STOCKTIPS_DB_NAME="${DB_NAME}"
"$PYTHON" - <<'PY'
import configparser
import os
from pathlib import Path
path = Path("config.ini")
cfg = configparser.ConfigParser()
cfg.read(path, encoding="utf-8")
values = {
    ("DATABASE", "HOST"): "localhost",
    ("DATABASE", "PORT"): "3306",
    ("DATABASE", "USER"): os.environ["STOCKTIPS_DB_USER"],
    ("DATABASE", "PASSWORD"): os.environ["STOCKTIPS_DB_PASSWORD"],
    ("DATABASE", "DATABASE"): os.environ["STOCKTIPS_DB_NAME"],
}
for (section, key), value in values.items():
    if section not in cfg:
        cfg[section] = {}
    cfg[section][key] = value
with path.open("w", encoding="utf-8") as f:
    cfg.write(f)
PY

echo "Creating .venv ..."
"$PYTHON" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo "Testing DB connection..."
python - <<'PY'
import configparser
import pymysql

config = configparser.ConfigParser()
config.read("config.ini")
db = {k.lower(): v for k, v in config["DATABASE"].items()}
conn = pymysql.connect(
    host=db["host"],
    port=int(db["port"]),
    user=db["user"],
    password=db["password"],
    database=db["database"],
    charset="utf8mb4",
)
conn.close()
print("MySQL OK:", db["database"], "@", db["host"], "as", db["user"])
PY

echo ""
echo "Environment created successfully!"
echo "Next:"
echo "  1) Set DISCORD.TOKEN / CHANNEL_ID / OWNER_IDS in config.ini"
echo "  2) Run manually:  ./start_project.bash"
echo "  OR production:   sudo ./deploy/install.sh   # systemd + auto-start"
exit 0
