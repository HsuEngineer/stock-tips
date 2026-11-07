from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import yfinance as yf


@dataclass
class Quote:
    ticker: str
    price: float
    open: float | None
    pct_vs_open: float | None


def normalize_tw_ticker(raw: str) -> str:
    code = raw.strip().upper()
    if not code:
        raise ValueError("Ticker is empty")
    if code.endswith(".TW") or code.endswith(".TWO"):
        return code
    if not code.replace(".", "").isalnum():
        raise ValueError(f"Invalid ticker: {raw}")
    return f"{code}.TW"


def _pct_vs_open(price: float, open_price: float | None) -> float | None:
    if open_price is None or open_price == 0:
        return None
    return (price - open_price) / open_price * 100.0


def fetch_quote(ticker: str) -> Quote | None:
    symbol = normalize_tw_ticker(ticker)
    try:
        t = yf.Ticker(symbol)
        info = {}
        try:
            info = t.fast_info or {}
        except Exception:
            info = {}

        price = None
        open_price = None

        if isinstance(info, dict):
            price = info.get("lastPrice") or info.get("last_price")
            open_price = info.get("open")
        else:
            price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
            open_price = getattr(info, "open", None)

        if price is None:
            hist = t.history(period="2d")
            if hist is None or hist.empty:
                return None
            price = float(hist["Close"].iloc[-1])
            open_price = float(hist["Open"].iloc[-1]) if "Open" in hist else None
        else:
            price = float(price)
            open_price = float(open_price) if open_price is not None else None
            if open_price is None:
                hist = t.history(period="1d")
                if hist is not None and not hist.empty and "Open" in hist:
                    open_price = float(hist["Open"].iloc[-1])

        return Quote(
            ticker=symbol,
            price=price,
            open=open_price,
            pct_vs_open=_pct_vs_open(price, open_price),
        )
    except Exception:
        return None


def fetch_quotes(tickers: Iterable[str]) -> dict[str, Quote]:
    symbols = []
    seen = set()
    for raw in tickers:
        try:
            symbol = normalize_tw_ticker(raw)
        except ValueError:
            continue
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    results: dict[str, Quote] = {}
    if not symbols:
        return results

    # Batch download for speed; fall back per-ticker if needed.
    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period="1d",
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception:
        data = None

    if data is None or getattr(data, "empty", True):
        for symbol in symbols:
            quote = fetch_quote(symbol)
            if quote:
                results[symbol] = quote
        return results

    # Single ticker: columns are OHLCV; multi: MultiIndex
    if len(symbols) == 1:
        symbol = symbols[0]
        try:
            row = data.iloc[-1]
            price = float(row["Close"])
            open_price = float(row["Open"]) if "Open" in row.index else None
            results[symbol] = Quote(
                ticker=symbol,
                price=price,
                open=open_price,
                pct_vs_open=_pct_vs_open(price, open_price),
            )
        except Exception:
            quote = fetch_quote(symbol)
            if quote:
                results[symbol] = quote
        return results

    for symbol in symbols:
        try:
            frame = data[symbol]
            if frame is None or frame.empty:
                continue
            row = frame.dropna(how="all").iloc[-1]
            price = float(row["Close"])
            open_price = float(row["Open"]) if "Open" in row.index else None
            results[symbol] = Quote(
                ticker=symbol,
                price=price,
                open=open_price,
                pct_vs_open=_pct_vs_open(price, open_price),
            )
        except Exception:
            quote = fetch_quote(symbol)
            if quote:
                results[symbol] = quote

    return results


def save_price_history(db, quotes: dict[str, Quote], fetched_at: datetime | None = None) -> None:
    when = fetched_at or datetime.now()
    rows = [
        (
            q.ticker,
            q.price,
            q.open,
            q.pct_vs_open,
            when,
        )
        for q in quotes.values()
    ]
    if not rows:
        return
    db.executemany(
        """
        INSERT INTO price_history (ticker, price, open, pct_vs_open, fetched_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        rows,
    )


def filter_sharp_movers(quotes: dict[str, Quote], threshold_pct: float) -> list[Quote]:
    movers = [
        q
        for q in quotes.values()
        if q.pct_vs_open is not None and abs(q.pct_vs_open) >= threshold_pct
    ]
    movers.sort(key=lambda q: abs(q.pct_vs_open or 0), reverse=True)
    return movers
