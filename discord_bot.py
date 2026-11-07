from __future__ import annotations

from datetime import date, datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

import constituents as constituents_mod
import portfolio as portfolio_mod
from stock import (
    fetch_quote,
    fetch_quotes,
    filter_sharp_movers,
    normalize_tw_ticker,
    save_price_history,
)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}"


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return datetime.strptime(raw, "%Y-%m-%d").date()


class StockTipsBot(commands.Bot):
    def __init__(
        self,
        *,
        db,
        stock_config: dict,
        channel_id: int,
        **kwargs,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, **kwargs)
        self.db = db
        self.stock_config = stock_config
        self.channel_id = channel_id
        self.poll_minutes = int(stock_config.get("poll_interval_minutes", 10))
        self.sharp_pct = float(stock_config.get("sharp_move_pct", 2.0))
        self.fund_id = str(stock_config.get("etf_fund_id", "1066"))
        months_raw = stock_config.get("constituent_refresh_months", "3,6,9,12")
        self.refresh_months = [int(x.strip()) for x in months_raw.split(",") if x.strip()]

    async def setup_hook(self) -> None:
        if not self.poll_loop.is_running():
            self.poll_loop.change_interval(minutes=self.poll_minutes)
            self.poll_loop.start()

    async def on_ready(self) -> None:
        print(f"Discord bot logged in as {self.user}")
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash command(s)")
        except Exception as e:
            print(f"Slash sync failed: {e}")

    @tasks.loop(minutes=10)
    async def poll_loop(self) -> None:
        await self.run_digest()

    @poll_loop.before_loop
    async def before_poll(self) -> None:
        await self.wait_until_ready()

    async def run_digest(self) -> None:
        channel = self.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self.channel_id)
            except Exception as e:
                print(f"Cannot resolve Discord channel: {e}")
                return

        try:
            constituents_mod.refresh_if_needed(
                self.db, self.fund_id, self.refresh_months, force=False
            )
        except Exception as e:
            print(f"Constituent refresh error: {e}")

        positions = portfolio_mod.list_positions(self.db)
        const_tickers = constituents_mod.constituent_tickers(self.db)
        tickers = {p["ticker"] for p in positions} | set(const_tickers)

        quotes = {}
        if tickers:
            try:
                quotes = fetch_quotes(tickers)
                save_price_history(self.db, quotes)
            except Exception as e:
                print(f"Quote fetch error: {e}")

        portfolio_rows = portfolio_mod.enrich_positions(positions, quotes)
        const_quotes = {t: quotes[t] for t in const_tickers if t in quotes}
        movers = filter_sharp_movers(const_quotes, self.sharp_pct)

        embed = discord.Embed(
            title="Stock Tips digest",
            description=f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            color=discord.Color.dark_teal(),
        )

        if portfolio_rows:
            lines = []
            for row in portfolio_rows:
                code = row["ticker"].replace(".TW", "")
                lines.append(
                    f"**{code}** qty {float(row['shares']):g} | "
                    f"avg {_fmt_money(float(row['avg_cost']))} | "
                    f"last {_fmt_money(row['last_price'])} | "
                    f"P&L {_fmt_money(row['unrealized_pnl'])} "
                    f"({_fmt_pct(row['pct_vs_avg'])}) | "
                    f"vs open {_fmt_pct(row['pct_vs_open'])} | "
                    f"bought {row['first_buy_date']}"
                )
            text = "\n".join(lines)
            if len(text) > 1000:
                text = text[:997] + "..."
            embed.add_field(name="My portfolio", value=text, inline=False)
        else:
            embed.add_field(
                name="My portfolio",
                value="No open positions. Use `/buy` to add one.",
                inline=False,
            )

        if movers:
            lines = []
            name_map = {
                r["ticker"]: r["name"] for r in constituents_mod.list_constituents(self.db)
            }
            for q in movers[:20]:
                code = q.ticker.replace(".TW", "")
                name = name_map.get(q.ticker, "")
                arrow = "▲" if (q.pct_vs_open or 0) >= 0 else "▼"
                lines.append(
                    f"{arrow} **{code}** {name} {_fmt_pct(q.pct_vs_open)} | "
                    f"open {_fmt_money(q.open)} → {_fmt_money(q.price)}"
                )
            embed.add_field(name="0050 sharp movers", value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name="0050 sharp movers",
                value=f"No movers ≥ {self.sharp_pct:g}% vs open.",
                inline=False,
            )

        await self._evaluate_alerts(channel, quotes)
        await channel.send(embed=embed)

    async def _evaluate_alerts(self, channel, quotes) -> None:
        rows = self.db.fetchall("SELECT * FROM alerts WHERE enabled = 1")
        for alert in rows:
            ticker = alert["ticker"]
            quote = quotes.get(ticker)
            if not quote:
                continue
            fired = False
            rule = alert["rule_type"]
            thr = float(alert["threshold"])
            if rule == "pct_vs_open" and quote.pct_vs_open is not None:
                fired = abs(quote.pct_vs_open) >= thr
            elif rule == "price_above":
                fired = quote.price >= thr
            elif rule == "price_below":
                fired = quote.price <= thr

            if not fired:
                continue
            last = alert.get("last_triggered_at")
            if last and (datetime.now() - last).total_seconds() < 3600:
                continue

            self.db.execute(
                "UPDATE alerts SET last_triggered_at = %s WHERE id = %s",
                (datetime.now(), alert["id"]),
            )
            await channel.send(
                f"Alert #{alert['id']}: **{ticker}** {rule} {thr} — "
                f"last {_fmt_money(quote.price)} vs open {_fmt_pct(quote.pct_vs_open)}"
            )


def create_bot(db, discord_config: dict, stock_config: dict) -> StockTipsBot:
    token = discord_config["token"]
    channel_id = int(discord_config["channel_id"])
    bot = StockTipsBot(db=db, stock_config=stock_config, channel_id=channel_id)

    @bot.tree.command(name="buy", description="Record a buy (odd lots OK)")
    @app_commands.describe(
        ticker="TW code e.g. 2330",
        shares="Share quantity (零股 OK)",
        price="Single fill price",
        trade_date="YYYY-MM-DD (optional)",
        note="Optional note",
    )
    async def buy(
        interaction: discord.Interaction,
        ticker: str,
        shares: float,
        price: float,
        trade_date: str | None = None,
        note: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            when = _parse_date(trade_date)
            pos = portfolio_mod.record_buy(bot.db, ticker, shares, price, when, note)
            await interaction.followup.send(
                f"Bought {shares:g} x {pos['ticker']} @ {price} — "
                f"avg cost {float(pos['avg_cost']):.4f}, qty {float(pos['shares']):g}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"Buy failed: {e}", ephemeral=True)

    @bot.tree.command(name="sell", description="Record a sell (odd lots OK)")
    @app_commands.describe(
        ticker="TW code e.g. 2330",
        shares="Share quantity",
        price="Single fill price",
        trade_date="YYYY-MM-DD (optional)",
        note="Optional note",
    )
    async def sell(
        interaction: discord.Interaction,
        ticker: str,
        shares: float,
        price: float,
        trade_date: str | None = None,
        note: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            when = _parse_date(trade_date)
            pos = portfolio_mod.record_sell(bot.db, ticker, shares, price, when, note)
            if pos is None:
                msg = f"Sold {shares:g} x {normalize_tw_ticker(ticker)} — position closed"
            else:
                msg = (
                    f"Sold {shares:g} x {pos['ticker']} @ {price} — "
                    f"remaining {float(pos['shares']):g}, avg {float(pos['avg_cost']):.4f}"
                )
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Sell failed: {e}", ephemeral=True)

    @bot.tree.command(name="portfolio", description="Show open positions with live P&L")
    async def portfolio_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        positions = portfolio_mod.list_positions(bot.db)
        if not positions:
            await interaction.followup.send("No open positions.", ephemeral=True)
            return
        quotes = fetch_quotes([p["ticker"] for p in positions])
        rows = portfolio_mod.enrich_positions(positions, quotes)
        lines = []
        for row in rows:
            lines.append(
                f"**{row['ticker']}** qty {float(row['shares']):g} | "
                f"avg {_fmt_money(float(row['avg_cost']))} | "
                f"last {_fmt_money(row['last_price'])} | "
                f"P&L {_fmt_money(row['unrealized_pnl'])} ({_fmt_pct(row['pct_vs_avg'])}) | "
                f"vs open {_fmt_pct(row['pct_vs_open'])} | "
                f"first buy {row['first_buy_date']}"
            )
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    @bot.tree.command(name="trades", description="Show recent buy/sell history")
    @app_commands.describe(ticker="Optional ticker filter")
    async def trades(interaction: discord.Interaction, ticker: str | None = None):
        await interaction.response.defer(ephemeral=True)
        rows = portfolio_mod.list_transactions(bot.db, ticker)
        if not rows:
            await interaction.followup.send("No trades found.", ephemeral=True)
            return
        lines = [
            f"#{r['id']} {r['trade_date']} {r['side'].upper()} {r['ticker']} "
            f"{float(r['shares']):g} @ {float(r['price']):.2f}"
            + (f" ({r['note']})" if r.get("note") else "")
            for r in rows[:30]
        ]
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    constituents = app_commands.Group(name="constituents", description="0050 constituents")

    @constituents.command(name="list", description="List current 0050 constituents")
    async def constituents_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = constituents_mod.list_constituents(bot.db)
        if not rows:
            await interaction.followup.send(
                "No constituents cached. Try `/constituents refresh`.",
                ephemeral=True,
            )
            return
        lines = [
            f"{r['ticker'].replace('.TW', '')} {r['name']} "
            f"({float(r['weight']) if r['weight'] is not None else 'n/a'}%)"
            for r in rows[:50]
        ]
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    @constituents.command(name="refresh", description="Force refresh 0050 from Yuanta")
    async def constituents_refresh(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            n = constituents_mod.refresh_if_needed(
                bot.db, bot.fund_id, bot.refresh_months, force=True
            )
            await interaction.followup.send(f"Refreshed {n} constituents.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Refresh failed: {e}", ephemeral=True)

    bot.tree.add_command(constituents)

    @bot.tree.command(name="quote", description="On-demand single-price quote")
    @app_commands.describe(ticker="TW code e.g. 2330")
    async def quote_cmd(interaction: discord.Interaction, ticker: str):
        await interaction.response.defer(ephemeral=True)
        q = fetch_quote(ticker)
        if not q:
            await interaction.followup.send(f"No quote for {ticker}", ephemeral=True)
            return
        await interaction.followup.send(
            f"**{q.ticker}** last {_fmt_money(q.price)} | "
            f"open {_fmt_money(q.open)} | vs open {_fmt_pct(q.pct_vs_open)}",
            ephemeral=True,
        )

    alert = app_commands.Group(name="alert", description="Custom price alerts")

    @alert.command(name="set", description="Set an alert")
    @app_commands.describe(
        ticker="TW code",
        rule_type="pct_vs_open | price_above | price_below",
        threshold="Threshold value",
    )
    @app_commands.choices(
        rule_type=[
            app_commands.Choice(name="pct_vs_open", value="pct_vs_open"),
            app_commands.Choice(name="price_above", value="price_above"),
            app_commands.Choice(name="price_below", value="price_below"),
        ]
    )
    async def alert_set(
        interaction: discord.Interaction,
        ticker: str,
        rule_type: app_commands.Choice[str],
        threshold: float,
    ):
        await interaction.response.defer(ephemeral=True)
        symbol = normalize_tw_ticker(ticker)
        alert_id = bot.db.execute(
            """
            INSERT INTO alerts (ticker, rule_type, threshold, enabled)
            VALUES (%s, %s, %s, 1)
            """,
            (symbol, rule_type.value, threshold),
        )
        await interaction.followup.send(
            f"Alert #{alert_id}: {symbol} {rule_type.value} {threshold}",
            ephemeral=True,
        )

    @alert.command(name="list", description="List alerts")
    async def alert_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = bot.db.fetchall("SELECT * FROM alerts ORDER BY id")
        if not rows:
            await interaction.followup.send("No alerts.", ephemeral=True)
            return
        lines = [
            f"#{r['id']} {r['ticker']} {r['rule_type']} {float(r['threshold'])} "
            f"{'on' if r['enabled'] else 'off'}"
            for r in rows
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @alert.command(name="remove", description="Remove an alert by id")
    async def alert_remove(interaction: discord.Interaction, alert_id: int):
        await interaction.response.defer(ephemeral=True)
        bot.db.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
        await interaction.followup.send(f"Removed alert #{alert_id}", ephemeral=True)

    bot.tree.add_command(alert)

    @bot.tree.command(name="digest", description="Run digest now")
    async def digest_now(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await bot.run_digest()
        await interaction.followup.send("Digest posted to channel.", ephemeral=True)

    # Keep token accessible for runner
    bot._stock_token = token  # noqa: SLF001
    return bot


def run_bot(bot: StockTipsBot) -> None:
    bot.run(bot._stock_token)
