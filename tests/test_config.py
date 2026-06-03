"""Tests for environment loading and validation in bot.config."""

import pytest

from bot.config import ConfigError, load_config

_FULL_ENV = {
    "TELEGRAM_BOT_TOKEN": "123:ABC",
    "GEMINI_API_KEY": "AIza-key",
    "GEMINI_MODEL": "gemini-flash",
    "BEANBALANCE_API_URL": "https://example.com/",
    "BEANBALANCE_EMAIL": "me@example.com",
    "BEANBALANCE_PASSWORD": "s3cret",
    "ALLOWED_TELEGRAM_IDS": "111, 222",
    "CONVERSATION_MEMORY_SIZE": "5",
}


def test_loads_all_fields_from_env() -> None:
    config = load_config(_FULL_ENV)

    assert config.telegram_bot_token == "123:ABC"
    assert config.gemini_api_key == "AIza-key"
    assert config.gemini_model == "gemini-flash"
    assert config.beanbalance_email == "me@example.com"
    assert config.beanbalance_password == "s3cret"
    assert config.allowed_telegram_ids == frozenset({111, 222})
    assert config.conversation_memory_size == 5


def test_strips_trailing_slash_from_api_url() -> None:
    config = load_config(_FULL_ENV)

    # Base URL must be clean so callers can append "/api/...".
    assert config.beanbalance_api_url == "https://example.com"


def test_applies_defaults_for_optional_vars() -> None:
    env = {k: v for k, v in _FULL_ENV.items()
           if k not in {"GEMINI_MODEL", "CONVERSATION_MEMORY_SIZE"}}

    config = load_config(env)

    assert config.gemini_model == "gemini-2.5-pro"
    assert config.conversation_memory_size == 10


def test_missing_required_var_names_the_variable() -> None:
    env = {k: v for k, v in _FULL_ENV.items() if k != "TELEGRAM_BOT_TOKEN"}

    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(env)


def test_blank_required_var_is_rejected() -> None:
    env = {**_FULL_ENV, "BEANBALANCE_PASSWORD": "   "}

    with pytest.raises(ConfigError, match="BEANBALANCE_PASSWORD"):
        load_config(env)


def test_allowlist_with_non_integer_id_reports_offending_value() -> None:
    env = {**_FULL_ENV, "ALLOWED_TELEGRAM_IDS": "111, oops"}

    with pytest.raises(ConfigError, match="oops"):
        load_config(env)


def test_empty_allowlist_is_rejected() -> None:
    env = {**_FULL_ENV, "ALLOWED_TELEGRAM_IDS": "  "}

    with pytest.raises(ConfigError, match="ALLOWED_TELEGRAM_IDS"):
        load_config(env)


def test_non_integer_memory_size_reports_offending_value() -> None:
    env = {**_FULL_ENV, "CONVERSATION_MEMORY_SIZE": "ten"}

    with pytest.raises(ConfigError, match="ten"):
        load_config(env)


def test_non_positive_memory_size_is_rejected() -> None:
    env = {**_FULL_ENV, "CONVERSATION_MEMORY_SIZE": "0"}

    with pytest.raises(ConfigError, match="CONVERSATION_MEMORY_SIZE"):
        load_config(env)
