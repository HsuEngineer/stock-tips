# Stock Tips

**Taiwan stock portfolio tracker + 0050 sharp-mover alerts — delivered in Discord every 10 minutes.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3+-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![MySQL](https://img.shields.io/badge/MySQL-8-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![yfinance](https://img.shields.io/badge/quotes-yfinance-lightgrey)](https://github.com/ranaroussi/yfinance)
[![Deploy](https://img.shields.io/badge/deploy-GCP%20VM-4285F4?logo=googlecloud&logoColor=white)](https://cloud.google.com/compute)

**English** · [繁體中文](README.zh-TW.md)

---

## Why this project?

If you already hold Taiwan stocks, you want a simple loop:

1. Record buys / sells (including **odd lots / 零股**)
2. See **average cost** and live P&L
3. Get nudged when **0050 constituents** move sharply vs the open

Stock Tips is a self-hosted Discord bot for that loop. No paid quote API. Runs on one GCP VM with MySQL beside it.

---

## Features

| | |
|---|---|
| **Personal portfolio** | `/buy` `/sell` with avg cost, first-buy date, unrealized P&L |
| **Scheduled digest** | Every **10 min**: your positions + 0050 sharp movers (≥ **2%** vs open, configurable) |
| **0050 context** | Yuanta constituent weights; refresh Mar / Jun / Sep / Dec (local seed fallback) |
| **On-demand quotes** | `/quote`, `/portfolio`, `/trades`, `/digest` |
| **Custom alerts** | % vs open, price above / below (1-hour cooldown) |
| **i18n** | `zh-TW` / `en` — switch with `/lang`; add locales by copying one JSON file |
| **Remote ops** | Owner-only `/update` `/restart` `/reboot` for GitHub + VM maintenance |

---

## Demo flow

```text
Discord channel  ←── digest every 10 min
       ▲
       │  slash commands (/buy, /quote, /alert …)
       │
   Stock Tips bot (Python)
       │
       ├── yfinance          → last price + open
       ├── Yuanta StkWeights → 0050 basket
       └── MySQL             → trades, positions, history, alerts
```

**Digest sections**

1. **My portfolio** — qty · avg · last · P&L · % vs avg · % vs open · first buy  
2. **0050 sharp movers** — names ≥ threshold vs open (or a short “none” line)

---

## Tech stack

| Layer | Choice |
|-------|--------|
| Runtime | Python 3.10+ |
| Bot | discord.py (slash commands + task loop) |
| Quotes | yfinance (single last price — no bid/ask) |
| 0050 list | Yuanta JSON API + `data/0050_constituents.json` |
| Storage | MySQL on the same VM |
| Host | GCP Compute Engine (Ubuntu) |
| Config | `config.ini` (gitignored) |

---

## Quick start (GCP — automated)

Full guide: **[deploy/README.md](deploy/README.md)**

### Option A — New VM in one command (recommended)

From your laptop / Cloud Shell (needs [`gcloud`](https://cloud.google.com/sdk/docs/install)):

```bash
git clone https://github.com/HsuEngineer/stock-tips.git
cd stock-tips
cp deploy/secrets.env.example deploy/secrets.env
nano deploy/secrets.env          # DISCORD_TOKEN, CHANNEL_ID, OWNER_IDS

chmod +x deploy/*.sh
./deploy/gcp-create-vm.sh        # creates VM + first-boot install
```

Watch install (~2–5 min):

```bash
gcloud compute ssh stock-tips --zone asia-east1-b \
  --command 'sudo tail -f /var/log/stocktips-startup.log'
```

Bot runs as **systemd** `stocktips.service` (survives reboot). Then in Discord: `/help` / `/digest`.

### Option B — Existing Ubuntu VM

```bash
git clone https://github.com/HsuEngineer/stock-tips.git
cd stock-tips
cp deploy/secrets.env.example deploy/secrets.env && nano deploy/secrets.env
chmod +x deploy/install.sh
sudo ./deploy/install.sh
sudo systemctl status stocktips
```

### Option C — Manual / tmux (no systemd)

```bash
./create_env.bash
nano config.ini                  # Discord values
tmux new -s stocktips './start_project.bash'
```

> **Owner ID:** Discord → Developer Mode → right-click avatar → Copy User ID.  
> Invite bot with scopes `bot` + `applications.commands`.

---

## Configuration

| Section | Keys | Purpose |
|---------|------|---------|
| `[DATABASE]` | `HOST` `PORT` `USER` `PASSWORD` `DATABASE` | MySQL |
| `[DISCORD]` | `TOKEN` `CHANNEL_ID` `OWNER_IDS` | Bot + digest channel + admins |
| `[STOCK]` | `POLL_INTERVAL_MINUTES` `SHARP_MOVE_PCT` `CONSTITUENT_REFRESH_MONTHS` `ETF_FUND_ID` | Poll & 0050 rules |
| `[APP]` | `LANGUAGE` | `zh-TW` (default) or `en` |

Optional passwordless reboot for `/reboot`:

```bash
sudo cp deploy/sudoers-stocktips.example /etc/sudoers.d/stocktips
sudo chmod 440 /etc/sudoers.d/stocktips
sudo visudo -cf /etc/sudoers.d/stocktips
```

---

## Discord commands

### Portfolio

| Command | Description |
|---------|-------------|
| `/buy` | Record buy (odd lots OK) — ticker, shares, price, optional date/note |
| `/sell` | Record sell — cannot exceed held shares |
| `/portfolio` | Open positions + live P&L |
| `/trades` | Recent ledger (optional ticker filter) |

```text
/buy ticker:2330 shares:10 price:980 trade_date:2024-01-15
```

### Market

| Command | Description |
|---------|-------------|
| `/quote` | Last / open / % vs open |
| `/constituents list` | Cached 0050 list |
| `/constituents refresh` | Force refresh |
| `/digest` | Post digest now |

### Alerts & settings

| Command | Description |
|---------|-------------|
| `/alert set` `/list` `/remove` | Custom thresholds |
| `/lang` | Switch `zh-TW` / `en` (also `!lang zh-TW`) |
| `/help` | Command guide (also `!help`) |

### Admin (`OWNER_IDS` only)

| Command | Description |
|---------|-------------|
| `/update` | Pull latest code from GitHub (`config.ini` kept) |
| `/restart` | Restart the Python process |
| `/reboot` | Reboot VM (`confirm=yes`) |

After you push to GitHub: `/update` → `/restart`.

### Keep the bot running

With `deploy/install.sh` or `gcp-create-vm.sh`, systemd owns the process:

```bash
sudo systemctl status stocktips
sudo journalctl -u stocktips -f
sudo systemctl restart stocktips
```

After Discord `/reboot`, the unit auto-starts. Manual fallback: `tmux new -s stocktips './start_project.bash'`.

---

## Portfolio math

| Rule | Formula / behavior |
|------|--------------------|
| Price used | Last traded price only |
| Avg cost (buy) | `(old_qty × old_avg + buy_qty × buy_price) / new_qty` |
| Sell | Keep avg on remainder; realized `+= (sell − avg) × sold` |
| Flat position | Row deleted; history stays in `transactions` |
| Lot size | Any positive qty (零股 OK) |

---

## Database schema

Created automatically on startup:

| Table | Role |
|-------|------|
| `transactions` | Buy/sell ledger (source of truth) |
| `positions` | Derived open holdings |
| `price_history` | Poll snapshots |
| `constituents` | 0050 tickers / weights |
| `alerts` | User alert rules |

---

## Project structure

```text
stock-tips/
├── main.py                 # Entry: config → DB → bot
├── discord_bot.py          # Slash commands + digest loop
├── portfolio.py / stock.py / constituents.py / database.py
├── i18n.py + locales/      # en / zh-TW
├── ops.py                  # /update /restart /reboot (systemd-aware)
├── deploy/
│   ├── README.md           # Full GCP automation guide
│   ├── gcp-create-vm.sh    # Create VM + auto-install
│   ├── gcp-startup.sh      # First-boot script
│   ├── install.sh          # Idempotent Ubuntu bootstrap
│   ├── stocktips.service   # systemd unit template
│   ├── secrets.env.example # Discord secrets template
│   └── sudoers-…           # reboot + systemctl
├── create_env.bash         # Light local bootstrap
├── start_project.bash      # Foreground run
├── README.md / README.zh-TW.md
└── DEVELOPER.md / PLAN.md
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Bot exits immediately | Set a real `DISCORD.TOKEN` in `config.ini` |
| No digests | Check `CHANNEL_ID` and bot send permissions |
| MySQL errors on new VM | Re-run `sudo ./deploy/install.sh` or `./create_env.bash` |
| Service won’t stay up | `sudo journalctl -u stocktips -n 80 --no-pager` |
| Slash commands missing | Wait for sync; re-invite with `applications.commands` |
| `/update` denied | Add your user id to `OWNER_IDS` |
| Empty movers | Market closed, or nothing ≥ threshold |

More detail: [DEVELOPER.md](DEVELOPER.md)

---

## Roadmap (ideas)

- Market-hours quiet mode & history retention  
- Transaction fees / realized P&L summary  
- Split Discord cogs + reconnect-safe DB  

GCP one-shot install + systemd auto-start after reboot is already in [deploy/](deploy/README.md).  
See [DEVELOPER.md](DEVELOPER.md) for the full improvement list.

---

## Disclaimer

For **personal tracking and learning** only — **not investment advice**. Free Yahoo quotes may be delayed or incomplete. Verify prices before you trade.

---

## License

Private / personal project unless a license file is added later.

---

## Links

- Repo: [HsuEngineer/stock-tips](https://github.com/HsuEngineer/stock-tips)  
- Chinese README: [README.zh-TW.md](README.zh-TW.md)  
- Maintainer notes: [DEVELOPER.md](DEVELOPER.md)
