from __future__ import annotations

import json
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"


def list_languages() -> list[str]:
    return sorted(p.stem for p in LOCALES_DIR.glob("*.json"))


def normalize_lang(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANG
    raw = lang.strip().replace("_", "-")
    # Accept zh, zh-tw, ZH-TW, etc.
    available = {x.lower(): x for x in list_languages()}
    key = raw.lower()
    if key in available:
        return available[key]
    # short form: zh -> zh-TW if present
    if key == "zh" and "zh-tw" in available:
        return available["zh-tw"]
    return DEFAULT_LANG


class I18n:
    """Simple JSON-file i18n. Add a new language by copying locales/en.json -> locales/xx.json."""

    def __init__(self, lang: str | None = None):
        self._fallback = self._load(DEFAULT_LANG)
        self.set_language(lang or DEFAULT_LANG)

    def _load(self, lang: str) -> dict[str, str]:
        path = LOCALES_DIR / f"{lang}.json"
        if not path.exists():
            # try normalized filename from available list
            norm = normalize_lang(lang)
            path = LOCALES_DIR / f"{norm}.json"
        if not path.exists():
            path = LOCALES_DIR / f"{DEFAULT_LANG}.json"
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Locale file must be a JSON object: {path}")
        return {str(k): str(v) for k, v in data.items()}

    def set_language(self, lang: str) -> str:
        self.lang = normalize_lang(lang)
        self._messages = self._load(self.lang)
        return self.lang

    def t(self, key: str, **kwargs) -> str:
        template = self._messages.get(key) or self._fallback.get(key) or key
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return template

    def side(self, side: str) -> str:
        return self.t(f"side.{side}") if side in ("buy", "sell") else side

    def rule(self, rule: str) -> str:
        key = f"rule.{rule}"
        return self.t(key) if key in self._messages or key in self._fallback else rule


def save_language_to_config(lang: str, config_path: str = "config.ini") -> None:
    """Persist LANGUAGE under [APP] in config.ini."""
    import configparser

    path = Path(config_path)
    config = configparser.ConfigParser()
    if path.exists():
        config.read(path, encoding="utf-8")
    if "APP" not in config:
        config["APP"] = {}
    config["APP"]["LANGUAGE"] = normalize_lang(lang)
    with path.open("w", encoding="utf-8") as f:
        config.write(f)
