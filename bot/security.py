"""Telegram user allowlist.

The bot acts as the owner's BeanBalance account, so only explicitly allowed
Telegram IDs may interact with it. Everything else is silently ignored.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Allowlist:
    """Immutable set of Telegram user IDs permitted to use the bot."""

    allowed_ids: frozenset[int]

    def is_authorized(self, user_id: int | None) -> bool:
        """Returns True only for a known, non-None Telegram user ID."""
        if user_id is None:
            return False
        return user_id in self.allowed_ids
