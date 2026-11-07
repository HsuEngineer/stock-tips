from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import requests

from stock import normalize_tw_ticker

YUANTA_URLS = [
    "https://www.yuantaetfs.com/api/StkWeights",
    "http://www.yuantaetfs.com/api/StkWeights",
]
SEED_PATH = Path(__file__).resolve().parent / "data" / "0050_constituents.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockTipsBot/1.0)",
    "Accept": "application/json, text/plain, */*",
}


def _normalize_rows(raw_rows: list) -> list[dict]:
    items = []
    for row in raw_rows:
        code = str(
            row.get("code")
            or row.get("Code")
            or row.get("ticker")
            or row.get("證券代號")
            or ""
        ).strip()
        if not code:
            continue
        name = str(
            row.get("name") or row.get("Name") or row.get("證券名稱") or ""
        ).strip()
        weight = row.get("weight", row.get("Weight"))
        try:
            ticker = normalize_tw_ticker(code)
        except ValueError:
            continue
        items.append(
            {
                "ticker": ticker,
                "name": name,
                "weight": float(weight) if weight is not None else None,
            }
        )
    return items


def _load_seed_file() -> list[dict]:
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Seed file missing: {SEED_PATH}")
    with SEED_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Seed file must be a JSON list")
    return _normalize_rows(data)


def _fetch_yuanta(fund_id: str) -> list[dict]:
    last_error = None
    for url in YUANTA_URLS:
        try:
            resp = requests.get(
                url,
                params={"date": "", "fundid": fund_id},
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            if "json" not in ctype and not resp.text.strip().startswith(("[", "{")):
                raise ValueError(f"Yuanta returned non-JSON ({ctype})")
            data = resp.json()
            if not isinstance(data, list) or not data:
                raise ValueError("Yuanta JSON was empty or not a list")
            items = _normalize_rows(data)
            if len(items) < 40:
                raise ValueError(f"Yuanta returned too few rows ({len(items)})")
            return items
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"Yuanta API unavailable: {last_error}")


def fetch_0050_constituents(fund_id: str = "1066") -> list[dict]:
    """Prefer live Yuanta JSON; fall back to bundled seed list."""
    try:
        items = _fetch_yuanta(fund_id)
        print(f"Fetched {len(items)} constituents from Yuanta.")
        return items
    except Exception as e:
        print(f"Yuanta fetch failed ({e}); using local seed file.")
        items = _load_seed_file()
        print(f"Loaded {len(items)} constituents from {SEED_PATH.name}.")
        return items


def upsert_constituents(db, items: list[dict], source: str = "0050") -> int:
    now = datetime.now()
    for item in items:
        db.execute(
            """
            INSERT INTO constituents (ticker, name, weight, source, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                weight = VALUES(weight),
                source = VALUES(source),
                updated_at = VALUES(updated_at)
            """,
            (item["ticker"], item["name"], item["weight"], source, now),
        )
    # Drop tickers no longer in the set
    tickers = [item["ticker"] for item in items]
    if tickers:
        placeholders = ",".join(["%s"] * len(tickers))
        db.execute(
            f"DELETE FROM constituents WHERE source = %s AND ticker NOT IN ({placeholders})",
            tuple([source, *tickers]),
        )
    return len(items)


def list_constituents(db) -> list[dict]:
    return db.fetchall(
        "SELECT ticker, name, weight, source, updated_at FROM constituents ORDER BY weight DESC, ticker"
    )


def constituent_tickers(db) -> list[str]:
    rows = db.fetchall("SELECT ticker FROM constituents ORDER BY ticker")
    return [r["ticker"] for r in rows]


def latest_update(db) -> datetime | None:
    row = db.fetchone("SELECT MAX(updated_at) AS updated_at FROM constituents")
    if not row or not row["updated_at"]:
        return None
    return row["updated_at"]


def should_refresh(db, refresh_months: list[int]) -> bool:
    updated = latest_update(db)
    if updated is None:
        return True
    now = datetime.now()
    if now.month in refresh_months and (
        updated.month != now.month or updated.year != now.year
    ):
        return True
    return (now - updated).days >= 40


def refresh_if_needed(db, fund_id: str, refresh_months: list[int], force: bool = False) -> int:
    if not force and not should_refresh(db, refresh_months):
        return 0
    items = fetch_0050_constituents(fund_id)
    return upsert_constituents(db, items)
