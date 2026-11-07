from __future__ import annotations

from datetime import date, datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import constituents as constituents_mod
import portfolio as portfolio_mod
from i18n import I18n, list_languages, save_language_to_config
from stock import (
    fetch_quote,
    fetch_quotes,
    filter_sharp_movers,
    normalize_tw_ticker,
    save_price_history,
)


def _fmt_pct(i18n: I18n, value: float | None) -> str:
    if value is None:
        return i18n.t("na")
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_money(i18n: I18n, value: float | None) -> str:
    if value is None:
        return i18n.t("na")
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
        i18n: I18n,
        **kwargs,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, **kwargs)
        self.db = db
        self.stock_config = stock_config
        self.channel_id = channel_id
        self.i18n = i18n
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
        print(f"Discord bot logged in as {self.user} (lang={self.i18n.lang})")
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
        t = self.i18n.t
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
        const_quotes = {x: quotes[x] for x in const_tickers if x in quotes}
        movers = filter_sharp_movers(const_quotes, self.sharp_pct)

        embed = discord.Embed(
            title=t("digest.title"),
            description=t(
                "digest.updated", time=datetime.now().strftime("%Y-%m-%d %H:%M")
            ),
            color=discord.Color.dark_teal(),
        )

        if portfolio_rows:
            lines = []
            for row in portfolio_rows:
                code = row["ticker"].replace(".TW", "")
                lines.append(
                    t(
                        "digest.portfolio_line",
                        code=code,
                        shares=float(row["shares"]),
                        avg=_fmt_money(self.i18n, float(row["avg_cost"])),
                        last=_fmt_money(self.i18n, row["last_price"]),
                        pnl=_fmt_money(self.i18n, row["unrealized_pnl"]),
                        pct_avg=_fmt_pct(self.i18n, row["pct_vs_avg"]),
                        pct_open=_fmt_pct(self.i18n, row["pct_vs_open"]),
                        first_buy=row["first_buy_date"],
                    )
                )
            text = "\n".join(lines)
            if len(text) > 1000:
                text = text[:997] + "..."
            embed.add_field(name=t("digest.portfolio"), value=text, inline=False)
        else:
            embed.add_field(
                name=t("digest.portfolio"),
                value=t("digest.portfolio_empty"),
                inline=False,
            )

        if movers:
            lines = []
            name_map = {
                r["ticker"]: r["name"] for r in constituents_mod.list_constituents(self.db)
            }
            for q in movers[:20]:
                code = q.ticker.replace(".TW", "")
                arrow = "▲" if (q.pct_vs_open or 0) >= 0 else "▼"
                lines.append(
                    t(
                        "digest.mover_line",
                        arrow=arrow,
                        code=code,
                        name=name_map.get(q.ticker, ""),
                        pct=_fmt_pct(self.i18n, q.pct_vs_open),
                        open=_fmt_money(self.i18n, q.open),
                        price=_fmt_money(self.i18n, q.price),
                    )
                )
            embed.add_field(name=t("digest.movers"), value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name=t("digest.movers"),
                value=t("digest.movers_empty", pct=self.sharp_pct),
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
                self.i18n.t(
                    "alert.fired",
                    id=alert["id"],
                    ticker=ticker,
                    rule=self.i18n.rule(rule),
                    threshold=thr,
                    price=_fmt_money(self.i18n, quote.price),
                    pct_open=_fmt_pct(self.i18n, quote.pct_vs_open),
                )
            )


def create_bot(
    db,
    discord_config: dict,
    stock_config: dict,
    i18n: I18n | None = None,
) -> StockTipsBot:
    token = discord_config["token"]
    channel_id = int(discord_config["channel_id"])
    i18n = i18n or I18n("en")
    bot = StockTipsBot(
        db=db, stock_config=stock_config, channel_id=channel_id, i18n=i18n
    )

    @bot.tree.command(name="buy", description=i18n.t("cmd.buy.desc"))
    @app_commands.describe(
        ticker=i18n.t("cmd.buy.ticker"),
        shares=i18n.t("cmd.buy.shares"),
        price=i18n.t("cmd.buy.price"),
        trade_date=i18n.t("cmd.buy.trade_date"),
        note=i18n.t("cmd.buy.note"),
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
                bot.i18n.t(
                    "cmd.buy.ok",
                    shares=shares,
                    ticker=pos["ticker"],
                    price=price,
                    avg=float(pos["avg_cost"]),
                    qty=float(pos["shares"]),
                ),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                bot.i18n.t("cmd.buy.fail", error=e), ephemeral=True
            )

    @bot.tree.command(name="sell", description=i18n.t("cmd.sell.desc"))
    @app_commands.describe(
        ticker=i18n.t("cmd.sell.ticker"),
        shares=i18n.t("cmd.sell.shares"),
        price=i18n.t("cmd.sell.price"),
        trade_date=i18n.t("cmd.sell.trade_date"),
        note=i18n.t("cmd.sell.note"),
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
                msg = bot.i18n.t(
                    "cmd.sell.closed",
                    shares=shares,
                    ticker=normalize_tw_ticker(ticker),
                )
            else:
                msg = bot.i18n.t(
                    "cmd.sell.ok",
                    shares=shares,
                    ticker=pos["ticker"],
                    price=price,
                    qty=float(pos["shares"]),
                    avg=float(pos["avg_cost"]),
                )
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                bot.i18n.t("cmd.sell.fail", error=e), ephemeral=True
            )

    @bot.tree.command(name="portfolio", description=i18n.t("cmd.portfolio.desc"))
    async def portfolio_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        positions = portfolio_mod.list_positions(bot.db)
        if not positions:
            await interaction.followup.send(
                bot.i18n.t("cmd.portfolio.empty"), ephemeral=True
            )
            return
        quotes = fetch_quotes([p["ticker"] for p in positions])
        rows = portfolio_mod.enrich_positions(positions, quotes)
        lines = [
            bot.i18n.t(
                "cmd.portfolio.line",
                ticker=row["ticker"],
                shares=float(row["shares"]),
                avg=_fmt_money(bot.i18n, float(row["avg_cost"])),
                last=_fmt_money(bot.i18n, row["last_price"]),
                pnl=_fmt_money(bot.i18n, row["unrealized_pnl"]),
                pct_avg=_fmt_pct(bot.i18n, row["pct_vs_avg"]),
                pct_open=_fmt_pct(bot.i18n, row["pct_vs_open"]),
                first_buy=row["first_buy_date"],
            )
            for row in rows
        ]
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    @bot.tree.command(name="trades", description=i18n.t("cmd.trades.desc"))
    @app_commands.describe(ticker=i18n.t("cmd.trades.ticker"))
    async def trades(interaction: discord.Interaction, ticker: str | None = None):
        await interaction.response.defer(ephemeral=True)
        rows = portfolio_mod.list_transactions(bot.db, ticker)
        if not rows:
            await interaction.followup.send(
                bot.i18n.t("cmd.trades.empty"), ephemeral=True
            )
            return
        lines = [
            bot.i18n.t(
                "cmd.trades.line",
                id=r["id"],
                date=r["trade_date"],
                side=bot.i18n.side(r["side"]),
                ticker=r["ticker"],
                shares=float(r["shares"]),
                price=float(r["price"]),
                note=f" ({r['note']})" if r.get("note") else "",
            )
            for r in rows[:30]
        ]
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    constituents = app_commands.Group(
        name="constituents", description=i18n.t("cmd.constituents.desc")
    )

    @constituents.command(name="list", description=i18n.t("cmd.constituents.list.desc"))
    async def constituents_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = constituents_mod.list_constituents(bot.db)
        if not rows:
            await interaction.followup.send(
                bot.i18n.t("cmd.constituents.list.empty"), ephemeral=True
            )
            return
        lines = [
            f"{r['ticker'].replace('.TW', '')} {r['name']} "
            f"({float(r['weight']) if r['weight'] is not None else bot.i18n.t('na')}%)"
            for r in rows[:50]
        ]
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    @constituents.command(
        name="refresh", description=i18n.t("cmd.constituents.refresh.desc")
    )
    async def constituents_refresh(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            n = constituents_mod.refresh_if_needed(
                bot.db, bot.fund_id, bot.refresh_months, force=True
            )
            await interaction.followup.send(
                bot.i18n.t("cmd.constituents.refresh.ok", count=n), ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                bot.i18n.t("cmd.constituents.refresh.fail", error=e), ephemeral=True
            )

    bot.tree.add_command(constituents)

    @bot.tree.command(name="quote", description=i18n.t("cmd.quote.desc"))
    @app_commands.describe(ticker=i18n.t("cmd.quote.ticker"))
    async def quote_cmd(interaction: discord.Interaction, ticker: str):
        await interaction.response.defer(ephemeral=True)
        q = fetch_quote(ticker)
        if not q:
            await interaction.followup.send(
                bot.i18n.t("cmd.quote.missing", ticker=ticker), ephemeral=True
            )
            return
        await interaction.followup.send(
            bot.i18n.t(
                "cmd.quote.ok",
                ticker=q.ticker,
                price=_fmt_money(bot.i18n, q.price),
                open=_fmt_money(bot.i18n, q.open),
                pct_open=_fmt_pct(bot.i18n, q.pct_vs_open),
            ),
            ephemeral=True,
        )

    alert = app_commands.Group(name="alert", description=i18n.t("cmd.alert.desc"))

    @alert.command(name="set", description=i18n.t("cmd.alert.set.desc"))
    @app_commands.describe(
        ticker=i18n.t("cmd.alert.set.ticker"),
        rule_type=i18n.t("cmd.alert.set.rule_type"),
        threshold=i18n.t("cmd.alert.set.threshold"),
    )
    @app_commands.choices(
        rule_type=[
            app_commands.Choice(
                name=i18n.t("cmd.alert.set.choice.pct"), value="pct_vs_open"
            ),
            app_commands.Choice(
                name=i18n.t("cmd.alert.set.choice.above"), value="price_above"
            ),
            app_commands.Choice(
                name=i18n.t("cmd.alert.set.choice.below"), value="price_below"
            ),
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
            bot.i18n.t(
                "cmd.alert.set.ok",
                id=alert_id,
                ticker=symbol,
                rule=bot.i18n.rule(rule_type.value),
                threshold=threshold,
            ),
            ephemeral=True,
        )

    @alert.command(name="list", description=i18n.t("cmd.alert.list.desc"))
    async def alert_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = bot.db.fetchall("SELECT * FROM alerts ORDER BY id")
        if not rows:
            await interaction.followup.send(
                bot.i18n.t("cmd.alert.list.empty"), ephemeral=True
            )
            return
        lines = [
            bot.i18n.t(
                "cmd.alert.list.line",
                id=r["id"],
                ticker=r["ticker"],
                rule=bot.i18n.rule(r["rule_type"]),
                threshold=float(r["threshold"]),
                enabled=bot.i18n.t("rule.enabled" if r["enabled"] else "rule.disabled"),
            )
            for r in rows
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @alert.command(name="remove", description=i18n.t("cmd.alert.remove.desc"))
    @app_commands.describe(alert_id=i18n.t("cmd.alert.remove.id"))
    async def alert_remove(interaction: discord.Interaction, alert_id: int):
        await interaction.response.defer(ephemeral=True)
        bot.db.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
        await interaction.followup.send(
            bot.i18n.t("cmd.alert.remove.ok", id=alert_id), ephemeral=True
        )

    bot.tree.add_command(alert)

    @bot.tree.command(name="digest", description=i18n.t("cmd.digest.desc"))
    async def digest_now(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await bot.run_digest()
        await interaction.followup.send(bot.i18n.t("cmd.digest.ok"), ephemeral=True)

    @bot.tree.command(name="lang", description=i18n.t("cmd.lang.desc"))
    @app_commands.describe(code=i18n.t("cmd.lang.code"))
    async def lang_cmd(interaction: discord.Interaction, code: str | None = None):
        await interaction.response.defer(ephemeral=True)
        available = ", ".join(list_languages())
        if not code:
            await interaction.followup.send(
                bot.i18n.t(
                    "cmd.lang.list", lang=bot.i18n.lang, available=available
                ),
                ephemeral=True,
            )
            return

        wanted = code.strip()
        known = {x.lower(): x for x in list_languages()}
        if wanted.lower() not in known and wanted.lower() not in ("zh",):
            await interaction.followup.send(
                bot.i18n.t("cmd.lang.fail", lang=wanted, available=available),
                ephemeral=True,
            )
            return

        new_lang = bot.i18n.set_language(wanted)
        try:
            save_language_to_config(new_lang)
        except Exception as e:
            print(f"Could not persist language: {e}")
        await interaction.followup.send(
            bot.i18n.t("cmd.lang.ok", lang=new_lang), ephemeral=True
        )

    bot._stock_token = token  # noqa: SLF001
    return bot


def run_bot(bot: StockTipsBot) -> None:
    bot.run(bot._stock_token)
