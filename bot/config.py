"""Loads and validates the bot's environment into a typed BotConfig.

Usage:
    from bot.config import load_config
    config = load_config(os.environ)
"""

from collections.abc import Mapping
from dataclasses import dataclass

_DEFAULT_MODEL = "gemini-2.5-pro"
_DEFAULT_MEMORY_SIZE = 10


class ConfigError(ValueError):
    """Raised when the environment is missing or has malformed values."""


@dataclass(frozen=True)
class BotConfig:
    telegram_bot_token: str
    gemini_api_key: str
    gemini_model: str
    beanbalance_api_url: str
    beanbalance_email: str
    beanbalance_password: str
    allowed_telegram_ids: frozenset[int]
    conversation_memory_size: int


def load_config(env: Mapping[str, str]) -> BotConfig:
    """Builds a BotConfig from an env mapping, raising ConfigError on bad input."""
    return BotConfig(
        telegram_bot_token=_required(env, "TELEGRAM_BOT_TOKEN"),
        gemini_api_key=_required(env, "GEMINI_API_KEY"),
        gemini_model=env.get("GEMINI_MODEL", "").strip() or _DEFAULT_MODEL,
        beanbalance_api_url=_required(env, "BEANBALANCE_API_URL").rstrip("/"),
        beanbalance_email=_required(env, "BEANBALANCE_EMAIL"),
        beanbalance_password=_required(env, "BEANBALANCE_PASSWORD"),
        allowed_telegram_ids=_parse_allowlist(env.get("ALLOWED_TELEGRAM_IDS", "")),
        conversation_memory_size=_parse_memory_size(
            env.get("CONVERSATION_MEMORY_SIZE", "")
        ),
    )


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required env var {key} (expected a non-empty string)")
    return value


def _parse_allowlist(raw: str) -> frozenset[int]:
    ids = {part.strip() for part in raw.split(",") if part.strip()}
    if not ids:
        raise ConfigError(
            "Empty ALLOWED_TELEGRAM_IDS (expected comma-separated Telegram IDs, e.g. '111,222')"
        )
    return frozenset(_to_id(part) for part in ids)


def _to_id(part: str) -> int:
    try:
        return int(part)
    except ValueError as exc:
        raise ConfigError(
            f"Invalid Telegram ID '{part}' in ALLOWED_TELEGRAM_IDS (expected an integer)"
        ) from exc


def _parse_memory_size(raw: str) -> int:
    value = raw.strip()
    if not value:
        return _DEFAULT_MEMORY_SIZE
    try:
        size = int(value)
    except ValueError as exc:
        raise ConfigError(
            f"Invalid CONVERSATION_MEMORY_SIZE '{value}' (expected a positive integer)"
        ) from exc
    if size < 1:
        raise ConfigError(
            f"Invalid CONVERSATION_MEMORY_SIZE '{value}' (expected a positive integer)"
        )
    return size
