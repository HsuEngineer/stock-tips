# Developer notes — Stock Tips

Internal guide for Daniel: **project history**, **what works well**, and **what to improve next**. User-facing docs: [README.md](README.md) (English) · [README.zh-TW.md](README.zh-TW.md) (繁中). GCP automation: [deploy/README.md](deploy/README.md). Product plan: [PLAN.md](PLAN.md).

---

## Project history (2026-11-07)

Built in one day from an empty scaffold into a GCP Discord bot. Evolution:

| Time (UTC+8) | Milestone |
|--------------|-----------|
| ~09:48 | Idea: poll stock prices every 10 min and notify via Discord. Requirements interview started. |
| ~09:53–10:07 | Locked: **TW only**, Discord bot (commands + digests), MySQL history, free data, **GCP VM**. Scope shifted to **0050 constituents** + sharp rise/fall vs open (Mar/Jun/Sep/Dec refresh). |
| ~10:07–10:22 | Priority became **personal portfolio** (avg cost, dates, buy/sell log). Chose **single last price** (no bid/ask), **yfinance** for quotes, **requests** for Yuanta JSON (no BeautifulSoup). Plan written to `PLAN.md`. |
| ~10:29–10:37 | Discussed Colab (not ideal for long-running Discord bots); **pushed to GitHub**. Initial commit `43fff20`. |
| ~11:33–11:39 | GCP fresh-VM pain: `python` missing, MySQL not installed / no DB. Fixed via richer `create_env.bash` + auto-create database in `database.py` (`66c68a7`). |
| ~13:54–14:19 | **i18n**: switchable `en` / `zh-TW`, `/lang`, autocomplete + `!lang` fallback; git-pull confusion on VM (local edits blocking pull) resolved. |
| ~14:22 | `/help` + `!help` with localized command list. |
| ~14:27–14:33 | Owner-only `/update`, `/restart`, `/reboot` + `ops.py` + sudoers example; explained why Discord `OWNER_IDS` is required. |

### Git commits (oldest → newest)

1. `43fff20` — Initial bot: portfolio, 0050, digest, MySQL schema  
2. `66c68a7` — Fresh-VM MySQL setup + auto-create `Stock` DB  
3. `d50cbfa` — i18n + `/lang` + locale files  
4. `8be9d44` — Lang UX: autocomplete + `!lang`  
5. `4eae10e` — `/help` + `!help`  
6. `714fae3` — `/update` `/restart` `/reboot` + `ops.py`  

### Design decisions that stuck

- Rename `discord.py` → `discord_bot.py` (avoids shadowing the `discord` package)  
- Taiwan tickers only; normalize to `####.TW`  
- Odd lots (零股) allowed  
- Digests always show portfolio + 0050 movers  
- `config.ini` gitignored so `/update` hard-reset does not wipe secrets  

---

## Architecture (current)

```
main.py
  └─ Database.init_schema()
  └─ constituents.refresh_if_needed()
  └─ discord_bot.create_bot() / run_bot()
        ├─ poll_loop → run_digest()
        │     fetch quotes → price_history → portfolio P&L → sharp movers → alerts → embed
        ├─ slash commands → portfolio / stock / constituents / alerts / i18n / ops
        └─ ops.py → git / execv restart / sudo reboot
```

| Module | Responsibility |
|--------|----------------|
| `main.py` | Config + wiring only |
| `database.py` | Connection, CRUD helpers, DDL |
| `portfolio.py` | Ledger + avg-cost math |
| `stock.py` | Quotes + history + movers filter |
| `constituents.py` | 0050 source of truth |
| `discord_bot.py` | UX surface (large) |
| `i18n.py` | Flat JSON key → format string |
| `ops.py` | Privileged host actions |

---

## What is already solid

- Clear split: portfolio math / quotes / constituents / Discord  
- Parameterized SQL via PyMySQL  
- Decimal-based share math for buys/sells  
- Yuanta + seed fallback for 0050  
- Batch `yfinance.download` with per-ticker fallback  
- Locale files make new languages cheap  
- Owner gate on destructive ops commands  

---

## Advice: methods / features worth adding

Priority order for the next iterations.

### 1. Reliability & ops (high)

| Idea | Why |
|------|-----|
| ~~**systemd unit**~~ | **Done** — `deploy/install.sh` + `stocktips.service` + `gcp-create-vm.sh` |
| **Market-hours gate** | Skip digests nights/weekends (TW session) to cut noise + yfinance load |
| **price_history retention** | Cron/job to delete rows older than N days — table grows every 10 min × ~50 tickers |
| **Health `/status`** | Last poll time, quote success rate, DB ping, uptime |
| **Safer `/update`** | Prefer `git pull --ff-only` or stash; hard reset is fine for “throwaway VM” but risky if you keep local patches |
| **Logging module** | Replace scattered `print()` with `logging` + rotate file under `/var/log` |

### 2. Portfolio / trading UX (high)

| Idea | Why |
|------|-----|
| **Fees / tax optional note fields or %** | Real TW fills include commission + tax; P&L is optimistic today |
| **`/realized` summary** | Surface `realized_pnl` already stored on positions |
| **Import CSV / paste ledger** | Faster than many `/buy` calls for existing holdings |
| **Per-user portfolios** | Today one shared DB = one person; multi-user needs `user_id` on transactions/positions |
| **Edit / undo last trade** | Mistyped `/buy` currently needs a compensating `/sell` or manual SQL |

### 3. Market / alerts (medium)

| Idea | Why |
|------|-----|
| **Watchlist outside 0050 + portfolio** | Track interest names without buying |
| **Alert cooldown config** | Hardcoded 1 hour in `_evaluate_alerts` |
| **Digest only when something changed** | Quiet channel when no movers and flat portfolio |
| **Intraday high/low optional** | Still one “last” price for cost basis; OHLC only for display |
| **TWO / ETF tickers** | `normalize_tw_ticker` already allows `.TWO`; product is TW-only but ETF (0050 itself) may be useful |

### 4. Code quality / structure (medium)

| Idea | Why |
|------|-----|
| **Split `discord_bot.py`** | ~680 lines; move command groups to `cogs/` (`portfolio_cog`, `alert_cog`, `ops_cog`) |
| **DB connection resilience** | Long-running bot: MySQL can drop idle connections — add reconnect / ping before queries |
| **Transactions for buy/sell** | `record_buy` / `record_sell` do multiple `execute` (each commits). One failed mid-way can desync ledger vs position. Use a single DB transaction / context manager |
| **Typed config object** | Replace ad-hoc `section_dict` + `.get` strings with a small dataclass |
| **Async quote fetch** | `fetch_quotes` blocks the event loop; wrap with `asyncio.to_thread` (you already do this for ops) |
| **Tests** | Unit tests for avg-cost / sell validation / `normalize_tw_ticker` / sharp-mover filter — pure logic, no Discord needed |

### 5. Later / out of scope for v1 (keep intentional)

- Brokerage sync, Cloud SQL, charts, paid quote APIs  
- BeautifulSoup scraping  
- Bid/ask  
- Multi-market (US/HK) until TW path is boringly stable  

---

## Advice: code that is better rewritten

Concrete hotspots — not “rewrite everything.”

### `database.py`

**Issues**

- Long-lived single connection + cursor; no reconnect after “MySQL server has gone away”  
- Every `execute` auto-commits — hard to do multi-statement atomic trades  
- `__del__` for cleanup is unreliable  

**Better direction**

```python
# Sketch: context-managed connection + optional transaction
with db.transaction():
    db.execute(...)  # insert tx
    db.execute(...)  # upsert position
```

Also consider a small connection pool (`pymysql` + ping) or connect-per-request for simplicity on a low-QPS bot.

### `portfolio.py` — `record_buy` / `record_sell`

**Issues**

- Not atomic across `transactions` + `positions`  
- Floats appear again in `enrich_positions` (OK for display; keep Decimal until the edge of Discord formatting)  

**Better direction**

- One transaction boundary  
- Optional: store quantities as `Decimal` in DB (already DECIMAL columns — good) and only `float()` when formatting  

### `stock.py` — `fetch_quote` / `fetch_quotes`

**Issues**

- Broad `except Exception: return None` hides rate limits / API changes  
- Mixing `fast_info`, `history`, and `download` is pragmatic but hard to debug  
- Blocking sync calls inside Discord async handlers  

**Better direction**

- Log failures with ticker + exception type  
- Always call quote helpers via `asyncio.to_thread` from the bot  
- Optionally cache quotes for 30–60s to avoid double-fetch (`/portfolio` during a poll)  

### `discord_bot.py`

**Issues**

- God-module: digest + all commands + admin  
- Nested closures in `create_bot` make testing awkward  
- Embed field cap (~1024 chars) already truncated; large portfolios will silently cut  

**Better direction**

- `commands.Cog` per domain  
- Paginate portfolio / trades / constituents (Discord buttons or multiple embeds)  
- Register commands as methods, inject `db` / `i18n` via bot attributes (already partly done)  

### `constituents.py` — `upsert_constituents`

**Issues**

- One `INSERT` per ticker (N round-trips)  
- Dynamic `DELETE ... NOT IN ({placeholders})` is fine for ~50 names; keep an eye on SQL length if the universe grows  

**Better direction**

- `executemany` for upserts  
- Or staging table + swap for cleaner refresh  

### `ops.py` — `git_update`

**Issues**

- `git reset --hard origin/master` discards any VM-only fixes  
- Branch name hardcoded to `master`  

**Better direction**

- Read branch from `git rev-parse --abbrev-ref HEAD`  
- Document “VM is disposable; all real changes go through GitHub” (current model) **or** soft-pull for safer ops  

### `i18n.py`

**Issues**

- Flat keys work; large `cmd.help.body` strings are painful to edit  
- Slash `description=` is fixed at command registration — language switch does not refresh Discord UI until restart (already documented — OK)  

**Better direction**

- Keep flat JSON (easy for contributors)  
- Or nested JSON + dotted keys if files get huge  
- Optionally re-sync the command tree after `/lang` (heavier; only if needed)  

### `create_env.bash`

**Issues**

- Default root password `P@ssw0rd` in script + example — fine for a private VM class project, **bad** if the VM is exposed  
- `sed` on `config.ini` can surprise if keys appear outside `[DATABASE]`  

**Better direction**

- Generate a random DB password on first run and print it once  
- Use a dedicated MySQL user with rights only on `Stock`  

---

## Suggested implementation order (next sprint)

1. Reconnect-safe DB + atomic buy/sell  
2. `asyncio.to_thread` for all yfinance / requests work from Discord  
3. Market-hours skip + `price_history` purge  
4. Split Discord cogs + `/status`  
5. Fees / realized summary / CSV import  
6. systemd unit for reboot resilience  

---

## How to extend safely

| Goal | Touch |
|------|--------|
| New slash command | `discord_bot.py` (or new cog) + keys in **both** `locales/*.json` |
| New language | Copy `locales/en.json` → `locales/xx.json` |
| New alert rule | MySQL `alerts.rule_type` ENUM + `_evaluate_alerts` + locale `rule.*` |
| Config knobs | `config.ini.example` + read in `main.py` / bot `__init__` |
| Schema change | `Database.init_schema` (and a one-off migration note — there is no migration runner yet) |

---

## Testing checklist (manual)

- [ ] `/buy` then `/portfolio` shows avg cost  
- [ ] Second `/buy` same ticker recalculates avg  
- [ ] `/sell` partial keeps avg; full sell removes position  
- [ ] Oversell rejected  
- [ ] `/digest` posts portfolio + movers  
- [ ] `/alert set` fires once, not every poll within an hour  
- [ ] `/lang zh-TW` / `en` changes replies  
- [ ] Non-owner `/update` denied; owner succeeds  
- [ ] After `/reboot`, bot comes back only if systemd/tmux auto-start is set  

---

## Chat reference

Full requirements thread: [Stock Tips Discord bot build](faf4094e-ce27-4ba8-b55c-1bb7a7b24b1c)
