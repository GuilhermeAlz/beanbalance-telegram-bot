"""JWT lifecycle against the BeanBalance auth microservice.

The bot logs in once with the owner's credentials, caches the token pair in
memory, and refreshes a few minutes before expiry. If a refresh is rejected
(token revoked/expired) it falls back to a fresh login.

Usage:
    provider = HttpTokenProvider(base_url, email, password, httpx.AsyncClient())
    auth = AuthClient(provider)
    headers = await auth.authorization_header()
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx


class AuthError(Exception):
    """Base error for authentication failures."""


class LoginError(AuthError):
    """Raised when login with email/password fails."""


class RefreshError(AuthError):
    """Raised when a token refresh is rejected by the server."""


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime  # timezone-aware (UTC)


class TokenProvider(Protocol):
    """Source of token pairs — abstracts the auth microservice for testing."""

    async def login(self) -> TokenSet: ...

    async def refresh(self, tokens: TokenSet) -> TokenSet: ...


_DEFAULT_MARGIN = timedelta(minutes=5)


class AuthClient:
    """Caches a TokenSet and decides when to reuse, refresh, or re-login."""

    def __init__(
        self,
        provider: TokenProvider,
        *,
        refresh_margin: timedelta = _DEFAULT_MARGIN,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = provider
        self._refresh_margin = refresh_margin
        self._now = now
        self._tokens: TokenSet | None = None

    async def authorization_header(self) -> dict[str, str]:
        """Returns a Bearer header backed by a currently-valid access token."""
        tokens = await self._valid_tokens()
        return {"Authorization": f"Bearer {tokens.access_token}"}

    async def _valid_tokens(self) -> TokenSet:
        if self._tokens is None:
            self._tokens = await self._provider.login()
            return self._tokens
        if self._is_expiring(self._tokens):
            self._tokens = await self._refresh_or_login(self._tokens)
        return self._tokens

    def _is_expiring(self, tokens: TokenSet) -> bool:
        return self._now() + self._refresh_margin >= tokens.expires_at

    async def _refresh_or_login(self, tokens: TokenSet) -> TokenSet:
        try:
            return await self._provider.refresh(tokens)
        except RefreshError:
            return await self._provider.login()


class HttpTokenProvider:
    """Talks to the auth MS over HTTP, wrapping httpx behind TokenProvider."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._client = client

    async def login(self) -> TokenSet:
        response = await self._client.post(
            f"{self._base_url}/api/auth/login",
            json={"email": self._email, "password": self._password},
        )
        if response.status_code != 200:
            raise LoginError(
                f"Login failed for {self._email} (HTTP {response.status_code}, "
                "expected 200 with token JSON)"
            )
        return _to_token_set(response.json())

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        response = await self._client.post(
            f"{self._base_url}/api/auth/refresh",
            json={
                "accessToken": tokens.access_token,
                "refreshToken": tokens.refresh_token,
            },
        )
        if response.status_code != 200:
            raise RefreshError(
                f"Refresh failed (HTTP {response.status_code}, expected 200 with token JSON)"
            )
        return _to_token_set(response.json())


def _to_token_set(data: dict[str, Any]) -> TokenSet:
    """Maps the auth MS AuthResponse (camelCase JSON) into a TokenSet."""
    try:
        return TokenSet(
            access_token=data["accessToken"],
            refresh_token=data["refreshToken"],
            expires_at=parse_expiration(data["expiration"]),
        )
    except KeyError as exc:
        raise AuthError(
            f"Malformed auth response {data!r} (expected keys accessToken, "
            "refreshToken, expiration)"
        ) from exc


_FRACTION = re.compile(r"\.(\d{1,6})\d*")


def parse_expiration(raw: str) -> datetime:
    """Parses a .NET UTC timestamp into an aware datetime.

    Handles a trailing 'Z' and >6 fractional digits, which Python 3.10's
    datetime.fromisoformat cannot. Example: parse_expiration("...T13:00:00Z").
    """
    text = raw.strip()
    text = re.sub("[Zz]$", "+00:00", text)
    text = _FRACTION.sub(lambda m: f".{m.group(1)}", text)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
