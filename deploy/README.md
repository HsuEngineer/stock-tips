# Deploy — GCP / Ubuntu automation

Three ways to get Stock Tips running. Prefer **A** if you have `gcloud` on your laptop.

| Path | When to use |
|------|-------------|
| **A. `gcp-create-vm.sh`** | New VM from scratch — create + auto-install |
| **B. `install.sh` on existing VM** | You already have an Ubuntu VM (SSH in once) |
| **C. `create_env.bash` + tmux** | Dev / manual (no systemd) |

---

## A) One-command new GCP VM

### 1. Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`)
- Billing-enabled GCP project
- Discord bot token, channel id, your user id

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Secrets

```bash
cp deploy/secrets.env.example deploy/secrets.env
nano deploy/secrets.env   # DISCORD_TOKEN / CHANNEL_ID / OWNER_IDS
```

`deploy/secrets.env` is gitignored — never commit it.

### 3. Create VM + install

```bash
chmod +x deploy/*.sh
./deploy/gcp-create-vm.sh
# or:
./deploy/gcp-create-vm.sh --project YOUR_PROJECT --zone asia-east1-b --name stock-tips
```

Default machine: `e2-small`, Ubuntu 22.04, disk 20GB, zone `asia-east1-b`.

### 4. Watch first boot

```bash
gcloud compute ssh stock-tips --zone asia-east1-b \
  --command 'sudo tail -f /var/log/stocktips-startup.log'
```

When you see `Install finished OK`:

```bash
gcloud compute ssh stock-tips --zone asia-east1-b \
  --command 'sudo systemctl status stocktips'
```

Then in Discord: `/help` or `/digest`.

### 5. Clear token from metadata (recommended)

```bash
gcloud compute instances remove-metadata stock-tips --zone asia-east1-b \
  --keys=stocktips-discord-token,stocktips-channel-id,stocktips-owner-ids
```

---

## B) Existing Ubuntu VM

```bash
git clone https://github.com/HsuEngineer/stock-tips.git
cd stock-tips
cp deploy/secrets.env.example deploy/secrets.env
nano deploy/secrets.env

chmod +x deploy/install.sh
sudo ./deploy/install.sh
# or pass env inline:
# sudo DISCORD_TOKEN=... DISCORD_CHANNEL_ID=... DISCORD_OWNER_IDS=... ./deploy/install.sh
```

Installs to `/opt/stock-tips`, enables `stocktips.service`, configures MySQL user `stocktips` (random password → `config.ini`).

```bash
sudo systemctl status stocktips
sudo journalctl -u stocktips -f
```

---

## C) Manual / tmux (no systemd)

```bash
./create_env.bash
nano config.ini    # Discord values
./start_project.bash
```

---

## Day-2 ops

| Action | Command |
|--------|---------|
| Logs | `sudo journalctl -u stocktips -f` |
| Restart | `sudo systemctl restart stocktips` or Discord `/restart` |
| Update code | Discord `/update` then `/restart` |
| Reboot VM | Discord `/reboot` (`confirm=yes`) — unit auto-starts |
| Edit config | `sudo nano /opt/stock-tips/config.ini` then restart |

---

## Files

| File | Role |
|------|------|
| `install.sh` | Idempotent full bootstrap on the VM |
| `gcp-create-vm.sh` | `gcloud` create instance + startup metadata |
| `gcp-startup.sh` | First-boot script (metadata → `install.sh`) |
| `stocktips.service` | systemd unit template |
| `sudoers-stocktips.example` | Passwordless reboot + systemctl |
| `secrets.env.example` | Template for Discord / DB secrets |
