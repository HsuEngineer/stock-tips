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

## Quick start

### 1. Clone & bootstrap (Ubuntu / GCP)

```bash
git clone https://github.com/HsuEngineer/stock-tips.git
cd stock-tips
chmod +x create_env.bash start_project.bash
./create_env.bash
```

The setup script installs Python/MySQL if needed, creates the `Stock` database, builds `.venv`, and installs dependencies.

### 2. Configure Discord

```bash
cp config.ini.example config.ini   # if not already created
nano config.ini
```

Set at least:

```ini
[DISCORD]
TOKEN=your_bot_token
CHANNEL_ID=1234567890
OWNER_IDS=your_discord_user_id
```

> **Owner ID:** Discord → Settings → Advanced → Developer Mode → right-click your avatar → Copy User ID.

Invite the bot with scopes: `bot` + `applications.commands`, and permission to send messages / embeds.

### 3. Run

```bash
tmux new -s stocktips './start_project.bash'
# Detach: Ctrl+B, then D
```

Then in Discord try `/help`, `/buy`, or `/digest`.

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
├── main.py              # Entry: config → DB → bot
├── discord_bot.py       # Slash commands + digest loop
├── portfolio.py         # Ledger & avg-cost
├── stock.py             # yfinance quotes
├── constituents.py      # 0050 fetch / cache
├── database.py          # MySQL + schema
├── i18n.py              # Locale loader
├── ops.py               # update / restart / reboot
├── locales/             # en.json, zh-TW.json
├── data/                # 0050 seed JSON
├── deploy/              # sudoers example
├── create_env.bash      # Fresh VM setup
├── start_project.bash   # Run bot
├── PLAN.md              # Product plan
├── DEVELOPER.md         # Maintainer notes
├── README.md            # English (this file)
└── README.zh-TW.md      # 繁體中文
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Bot exits immediately | Set a real `DISCORD.TOKEN` in `config.ini` |
| No digests | Check `CHANNEL_ID` and bot send permissions |
| MySQL errors on new VM | Re-run `./create_env.bash` |
| Slash commands missing | Wait for sync; re-invite with `applications.commands` |
| `/update` denied | Add your user id to `OWNER_IDS` |
| Empty movers | Market closed, or nothing ≥ threshold |

More detail: [DEVELOPER.md](DEVELOPER.md)

---

## Roadmap (ideas)

- Market-hours quiet mode & history retention  
- Transaction fees / realized P&L summary  
- Split Discord cogs + reconnect-safe DB  
- systemd unit for auto-start after reboot  

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
