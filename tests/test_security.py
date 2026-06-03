"""Tests for the Telegram ID allowlist in bot.security."""

from bot.security import Allowlist

_ALLOWLIST = Allowlist(frozenset({111, 222}))


def test_authorized_id_is_allowed() -> None:
    assert _ALLOWLIST.is_authorized(111) is True


def test_unknown_id_is_rejected() -> None:
    assert _ALLOWLIST.is_authorized(999) is False


def test_missing_user_id_is_rejected() -> None:
    # update.effective_user can be None for some update types.
    assert _ALLOWLIST.is_authorized(None) is False
