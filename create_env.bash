#!/bin/bash
set -euo pipefail

USER=root
PASSWORD=00000000

echo "Creating config.ini from example (keeps existing if already present)..."
if [ ! -f config.ini ]; then
  cp config.ini.example config.ini
  sed -i "s/your_password/$PASSWORD/g" config.ini
  sed -i "s/^USER=.*/USER=$USER/g" config.ini
fi

echo "Creating .venv ..."
python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt

echo "Environment created successfully!"
echo "Next: edit config.ini (DATABASE + DISCORD.TOKEN + DISCORD.CHANNEL_ID), ensure MySQL DB exists, then ./start_project.bash"
exit 0
