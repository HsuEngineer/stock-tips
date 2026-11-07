#!/bin/bash
set -euo pipefail

# Defaults for a fresh GCP VM (edit if needed)
DB_USER=root
DB_PASSWORD=P@ssw0rd
DB_NAME=Stock

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Installing Python..."
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv
  PYTHON=python3
fi

echo "Using: $PYTHON ($($PYTHON --version 2>&1))"

echo "Installing MySQL server (if needed)..."
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server

echo "Starting MySQL..."
sudo systemctl enable mysql
sudo systemctl start mysql

echo "Configuring MySQL root password and database '${DB_NAME}'..."
# Ubuntu MySQL root often uses auth_socket; allow password login from localhost for this app
sudo mysql -e "
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${DB_PASSWORD}';
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
FLUSH PRIVILEGES;
" || sudo mysql -e "
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"

echo "Creating config.ini from example (keeps existing if already present)..."
if [ ! -f config.ini ]; then
  cp config.ini.example config.ini
fi
# Always sync DB settings into config.ini for this VM
sed -i "s/^HOST=.*/HOST=localhost/g" config.ini
sed -i "s/^PORT=.*/PORT=3306/g" config.ini
sed -i "s/^USER=.*/USER=${DB_USER}/g" config.ini
sed -i "s/^PASSWORD=.*/PASSWORD=${DB_PASSWORD}/g" config.ini
sed -i "s/^DATABASE=.*/DATABASE=${DB_NAME}/g" config.ini

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
print("MySQL OK:", db["database"], "@", db["host"])
PY

echo "Environment created successfully!"
echo "Next: set DISCORD.TOKEN and DISCORD.CHANNEL_ID in config.ini, then ./start_project.bash"
exit 0
