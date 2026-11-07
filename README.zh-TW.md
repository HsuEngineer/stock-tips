# Stock Tips

**台灣持股追蹤 + 0050 急漲急跌提醒 — 每 10 分鐘透過 Discord 推播。**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3+-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![MySQL](https://img.shields.io/badge/MySQL-8-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![yfinance](https://img.shields.io/badge/quotes-yfinance-lightgrey)](https://github.com/ranaroussi/yfinance)
[![Deploy](https://img.shields.io/badge/deploy-GCP%20VM-4285F4?logo=googlecloud&logoColor=white)](https://cloud.google.com/compute)

[English](README.md) · **繁體中文**

---

## 為什麼做這個專案？

如果你已經持有台股，通常只想要一個簡單循環：

1. 記錄買進 / 賣出（含 **零股**）
2. 看到 **成本均價** 與即時損益
3. 當 **0050 成分股** 相對開盤急漲急跌時被提醒

Stock Tips 是自架的 Discord 機器人，專門做這件事。不用付費報價 API，一台 GCP VM + 本機 MySQL 就能跑。

---

## 功能特色

| | |
|---|---|
| **個人持股** | `/buy` `/sell`：均價、首買日、未實現損益 |
| **定期摘要** | 每 **10 分鐘**：持股 + 0050 急漲急跌（相對開盤 ≥ **2%**，可調） |
| **0050 成分** | 元大成分股權重；3 / 6 / 9 / 12 月更新（本機種子檔備援） |
| **即時查詢** | `/quote`、`/portfolio`、`/trades`、`/digest` |
| **自訂警報** | 相對開盤%、股價高於 / 低於（每小時最多觸發一次） |
| **多語系** | `zh-TW` / `en`，用 `/lang` 切換；新增語言只要複製一份 JSON |
| **遠端維運** | 僅管理員：`/update` `/restart` `/reboot` |

---

## 運作示意

```text
Discord 頻道  ←── 每 10 分鐘摘要
       ▲
       │  斜線指令（/buy、/quote、/alert …）
       │
   Stock Tips 機器人（Python）
       │
       ├── yfinance          → 現價 + 開盤價
       ├── 元大 StkWeights   → 0050 成分
       └── MySQL             → 成交、持股、行情歷史、警報
```

**摘要內容**

1. **我的持股** — 股數 · 均價 · 現價 · 損益 · 較均價% · 較開盤% · 首買日  
2. **0050 急漲急跌** — 達門檻的成分股（若無則顯示簡短說明）

---

## 技術架構

| 層級 | 選用 |
|------|------|
| 執行環境 | Python 3.10+ |
| 機器人 | discord.py（斜線指令 + 排程迴圈） |
| 報價 | yfinance（僅成交價，無買賣價） |
| 0050 清單 | 元大 JSON API + `data/0050_constituents.json` |
| 儲存 | 同機 MySQL |
| 主機 | GCP Compute Engine（Ubuntu） |
| 設定 | `config.ini`（已加入 `.gitignore`） |

---

## 快速開始

### 1. 下載並初始化（Ubuntu / GCP）

```bash
git clone https://github.com/HsuEngineer/stock-tips.git
cd stock-tips
chmod +x create_env.bash start_project.bash
./create_env.bash
```

腳本會視需要安裝 Python / MySQL、建立 `Stock` 資料庫、建立 `.venv` 並安裝依賴。

### 2. 設定 Discord

```bash
cp config.ini.example config.ini   # 若尚未產生
nano config.ini
```

至少填入：

```ini
[DISCORD]
TOKEN=your_bot_token
CHANNEL_ID=1234567890
OWNER_IDS=你的Discord使用者ID
```

> **取得使用者 ID：** Discord → 設定 → 進階 → 開啟開發者模式 → 右鍵自己的頭像 → 複製使用者 ID。

邀請機器人時請勾選：`bot` + `applications.commands`，並給予傳送訊息 / 嵌入內容權限。

### 3. 啟動

```bash
tmux new -s stocktips './start_project.bash'
# 離開工作階段：Ctrl+B，再按 D
```

接著在 Discord 試試 `/help`、`/buy` 或 `/digest`。

---

## 設定說明

| 區段 | 欄位 | 用途 |
|------|------|------|
| `[DATABASE]` | `HOST` `PORT` `USER` `PASSWORD` `DATABASE` | MySQL 連線 |
| `[DISCORD]` | `TOKEN` `CHANNEL_ID` `OWNER_IDS` | 機器人、推播頻道、管理員 |
| `[STOCK]` | `POLL_INTERVAL_MINUTES` `SHARP_MOVE_PCT` `CONSTITUENT_REFRESH_MONTHS` `ETF_FUND_ID` | 輪詢與 0050 規則 |
| `[APP]` | `LANGUAGE` | 預設 `zh-TW`，或 `en` |

若要使用 `/reboot`（免密碼重開機）：

```bash
sudo cp deploy/sudoers-stocktips.example /etc/sudoers.d/stocktips
sudo chmod 440 /etc/sudoers.d/stocktips
sudo visudo -cf /etc/sudoers.d/stocktips
```

---

## Discord 指令

### 持股

| 指令 | 說明 |
|------|------|
| `/buy` | 記錄買進（可零股）— 代號、股數、單價、選填日期/備註 |
| `/sell` | 記錄賣出 — 不可超過持股 |
| `/portfolio` | 目前持股與即時損益 |
| `/trades` | 近期買賣紀錄（可篩選代號） |

```text
/buy ticker:2330 shares:10 price:980 trade_date:2024-01-15
```

### 行情

| 指令 | 說明 |
|------|------|
| `/quote` | 現價 / 開盤 / 較開盤% |
| `/constituents list` | 目前快取的 0050 清單 |
| `/constituents refresh` | 強制更新 |
| `/digest` | 立刻推播一次摘要 |

### 警報與設定

| 指令 | 說明 |
|------|------|
| `/alert set` `/list` `/remove` | 自訂門檻警報 |
| `/lang` | 切換 `zh-TW` / `en`（也可用 `!lang zh-TW`） |
| `/help` | 指令說明（也可用 `!help`） |

### 管理（僅 `OWNER_IDS`）

| 指令 | 說明 |
|------|------|
| `/update` | 從 GitHub 更新程式（保留 `config.ini`） |
| `/restart` | 重啟 Python 行程 |
| `/reboot` | 重開機 VM（需 `confirm=yes`） |

推程式到 GitHub 後：先 `/update`，再 `/restart`。

---

## 成本與損益計算

| 規則 | 行為 |
|------|------|
| 使用價格 | 僅最後成交價 |
| 買進均價 | `(原股數 × 原均價 + 買進股數 × 買進價) / 新股數` |
| 賣出 | 剩餘部位保留均價；已實現損益 `+= (賣價 − 均價) × 賣出股數` |
| 清倉 | 刪除持股列；成交紀錄仍留在 `transactions` |
| 張數 | 任意正數股數（零股 OK） |

---

## 資料庫

啟動時自動建表：

| 資料表 | 用途 |
|--------|------|
| `transactions` | 買賣流水（真實來源） |
| `positions` | 目前持股（由流水推導） |
| `price_history` | 輪詢行情快照 |
| `constituents` | 0050 成分與權重 |
| `alerts` | 自訂警報 |

---

## 專案結構

```text
stock-tips/
├── main.py              # 入口：設定 → 資料庫 → 機器人
├── discord_bot.py       # 斜線指令 + 摘要排程
├── portfolio.py         # 成交與均價
├── stock.py             # yfinance 報價
├── constituents.py      # 0050 抓取 / 快取
├── database.py          # MySQL 與 schema
├── i18n.py              # 語系載入
├── ops.py               # update / restart / reboot
├── locales/             # en.json、zh-TW.json
├── data/                # 0050 種子資料
├── deploy/              # sudoers 範例
├── create_env.bash      # 新 VM 一鍵環境
├── start_project.bash   # 啟動機器人
├── PLAN.md              # 產品規劃
├── DEVELOPER.md         # 維護者筆記
├── README.md            # English
└── README.zh-TW.md      # 繁體中文（本檔）
```

---

## 疑難排解

| 現象 | 處理 |
|------|------|
| 機器人立刻結束 | 在 `config.ini` 填入真實 `DISCORD.TOKEN` |
| 沒有摘要訊息 | 檢查 `CHANNEL_ID` 與機器人發言權限 |
| 新 VM MySQL 連不上 | 再執行一次 `./create_env.bash` |
| 看不到斜線指令 | 等同步；用含 `applications.commands` 的連結重邀 |
| `/update` 被拒 | 把你的使用者 ID 加進 `OWNER_IDS` |
| 急漲急跌為空 | 休市，或沒有標的達門檻 |

更多細節見 [DEVELOPER.md](DEVELOPER.md)。

---

## 之後可加強（構想）

- 開盤時段才推播、行情歷史自動清理  
- 手續費 / 已實現損益總覽  
- Discord cog 拆分、資料庫斷線重連  
- systemd 開機自啟  

完整清單見 [DEVELOPER.md](DEVELOPER.md)。

---

## 免責聲明

本專案僅供 **個人追蹤與學習**，**非投資建議**。Yahoo 免費報價可能延遲或不完整。實際下單前請自行核對行情。

---

## 授權

目前為私人 / 個人專案；之後若新增授權檔再另行說明。

---

## 相關連結

- 專案倉庫：[HsuEngineer/stock-tips](https://github.com/HsuEngineer/stock-tips)  
- English README：[README.md](README.md)  
- 維護筆記：[DEVELOPER.md](DEVELOPER.md)
