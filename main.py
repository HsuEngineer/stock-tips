import configparser
import sys
from pathlib import Path

from constituents import refresh_if_needed
from database import Database
from discord_bot import create_bot, run_bot


def load_config(path: str = "config.ini") -> configparser.ConfigParser:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.ini.example to config.ini and fill in values."
        )
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    return config


def section_dict(config: configparser.ConfigParser, name: str) -> dict:
    if name not in config:
        raise KeyError(f"Missing [{name}] section in config.ini")
    return {k.lower(): v for k, v in config[name].items()}


def main() -> None:
    print("Stock Tips starting...")
    config = load_config()

    db_cfg = section_dict(config, "DATABASE")
    discord_cfg = section_dict(config, "DISCORD")
    stock_cfg = section_dict(config, "STOCK")

    db = Database(db_cfg)
    db.init_schema()
    print("Database schema ready.")

    months = [
        int(x.strip())
        for x in stock_cfg.get("constituent_refresh_months", "3,6,9,12").split(",")
        if x.strip()
    ]
    try:
        n = refresh_if_needed(
            db,
            fund_id=stock_cfg.get("etf_fund_id", "1066"),
            refresh_months=months,
            force=False,
        )
        if n:
            print(f"Loaded/refreshed {n} 0050 constituents.")
        else:
            print("0050 constituents cache is fresh.")
    except Exception as e:
        print(f"Warning: could not refresh 0050 constituents yet: {e}")

    if not discord_cfg.get("token") or discord_cfg.get("token") == "your_bot_token":
        print("Set DISCORD.TOKEN in config.ini before starting the bot.")
        sys.exit(1)

    bot = create_bot(db, discord_cfg, stock_cfg)
    print(
        f"Bot ready. Poll every {stock_cfg.get('poll_interval_minutes', 10)} min; "
        f"sharp move ≥ {stock_cfg.get('sharp_move_pct', 2.0)}%."
    )
    run_bot(bot)


if __name__ == "__main__":
    main()
