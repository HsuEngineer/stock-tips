from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from stock import Quote, normalize_tw_ticker


def _to_decimal(value) -> Decimal:
    return Decimal(str(value))


def get_position(db, ticker: str) -> dict | None:
    symbol = normalize_tw_ticker(ticker)
    return db.fetchone("SELECT * FROM positions WHERE ticker = %s", (symbol,))


def list_positions(db) -> list[dict]:
    return db.fetchall("SELECT * FROM positions ORDER BY ticker")


def list_transactions(db, ticker: str | None = None, limit: int = 50) -> list[dict]:
    if ticker:
        symbol = normalize_tw_ticker(ticker)
        return db.fetchall(
            """
            SELECT * FROM transactions
            WHERE ticker = %s
            ORDER BY trade_date DESC, id DESC
            LIMIT %s
            """,
            (symbol, limit),
        )
    return db.fetchall(
        """
        SELECT * FROM transactions
        ORDER BY trade_date DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    )


def record_buy(
    db,
    ticker: str,
    shares,
    price,
    trade_date: date | None = None,
    note: str | None = None,
) -> dict:
    symbol = normalize_tw_ticker(ticker)
    qty = _to_decimal(shares)
    fill = _to_decimal(price)
    if qty <= 0 or fill <= 0:
        raise ValueError("shares and price must be positive")

    when = trade_date or date.today()
    pos = get_position(db, symbol)

    if pos is None:
        new_shares = qty
        avg_cost = fill
        first_buy = when
        realized = Decimal("0")
    else:
        old_shares = _to_decimal(pos["shares"])
        old_avg = _to_decimal(pos["avg_cost"])
        new_shares = old_shares + qty
        avg_cost = (old_shares * old_avg + qty * fill) / new_shares
        first_buy = pos["first_buy_date"]
        realized = _to_decimal(pos["realized_pnl"])

    db.execute(
        """
        INSERT INTO transactions (ticker, side, shares, price, trade_date, note, created_at)
        VALUES (%s, 'buy', %s, %s, %s, %s, %s)
        """,
        (symbol, qty, fill, when, note, datetime.now()),
    )
    db.execute(
        """
        INSERT INTO positions (ticker, shares, avg_cost, first_buy_date, last_trade_date, realized_pnl)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            shares = VALUES(shares),
            avg_cost = VALUES(avg_cost),
            last_trade_date = VALUES(last_trade_date),
            realized_pnl = VALUES(realized_pnl)
        """,
        (symbol, new_shares, avg_cost, first_buy, when, realized),
    )
    return get_position(db, symbol)


def record_sell(
    db,
    ticker: str,
    shares,
    price,
    trade_date: date | None = None,
    note: str | None = None,
) -> dict | None:
    symbol = normalize_tw_ticker(ticker)
    qty = _to_decimal(shares)
    fill = _to_decimal(price)
    if qty <= 0 or fill <= 0:
        raise ValueError("shares and price must be positive")

    when = trade_date or date.today()
    pos = get_position(db, symbol)
    if pos is None:
        raise ValueError(f"No open position for {symbol}")

    old_shares = _to_decimal(pos["shares"])
    if qty > old_shares:
        raise ValueError(f"Cannot sell {qty}; only {old_shares} shares held")

    avg_cost = _to_decimal(pos["avg_cost"])
    realized = _to_decimal(pos["realized_pnl"]) + (fill - avg_cost) * qty
    new_shares = old_shares - qty

    db.execute(
        """
        INSERT INTO transactions (ticker, side, shares, price, trade_date, note, created_at)
        VALUES (%s, 'sell', %s, %s, %s, %s, %s)
        """,
        (symbol, qty, fill, when, note, datetime.now()),
    )

    if new_shares <= 0:
        db.execute("DELETE FROM positions WHERE ticker = %s", (symbol,))
        return None

    db.execute(
        """
        UPDATE positions
        SET shares = %s, last_trade_date = %s, realized_pnl = %s
        WHERE ticker = %s
        """,
        (new_shares, when, realized, symbol),
    )
    return get_position(db, symbol)


def enrich_positions(positions: list[dict], quotes: dict[str, Quote]) -> list[dict]:
    enriched = []
    for pos in positions:
        ticker = pos["ticker"]
        quote = quotes.get(ticker)
        shares = float(pos["shares"])
        avg_cost = float(pos["avg_cost"])
        last = quote.price if quote else None
        pct_vs_avg = None
        unrealized = None
        pct_vs_open = quote.pct_vs_open if quote else None
        if last is not None:
            unrealized = (last - avg_cost) * shares
            if avg_cost:
                pct_vs_avg = (last - avg_cost) / avg_cost * 100.0
        enriched.append(
            {
                **pos,
                "last_price": last,
                "unrealized_pnl": unrealized,
                "pct_vs_avg": pct_vs_avg,
                "pct_vs_open": pct_vs_open,
                "open": quote.open if quote else None,
            }
        )
    return enriched
