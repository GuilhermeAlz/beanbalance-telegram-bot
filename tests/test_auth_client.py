"""Tests for JWT lifecycle management in bot.auth_client."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from bot.auth_client import (
    AuthClient,
    HttpTokenProvider,
    LoginError,
    RefreshError,
    TokenSet,
    parse_expiration,
)

_NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def _token(access: str, *, expires_in_min: int, refresh: str = "r1") -> TokenSet:
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        expires_at=_NOW + timedelta(minutes=expires_in_min),
    )


class FakeTokenProvider:
    """Named fake standing in for the auth microservice round-trips."""

    def __init__(self, login_tokens: list[TokenSet]) -> None:
        self._login_tokens = list(login_tokens)
        self.refresh_result: TokenSet | None = None
        self.refresh_should_fail = False
        self.login_calls = 0
        self.refresh_calls = 0

    async def login(self) -> TokenSet:
        self.login_calls += 1
        return self._login_tokens.pop(0)

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        self.refresh_calls += 1
        if self.refresh_should_fail:
            raise RefreshError("refresh rejected")
        assert self.refresh_result is not None
        return self.refresh_result


class MovableClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


# ── AuthClient policy ──────────────────────────────────────────────


async def test_first_call_logs_in_and_returns_bearer_header() -> None:
    provider = FakeTokenProvider([_token("a1", expires_in_min=60)])
    client = AuthClient(provider, now=MovableClock(_NOW))

    header = await client.authorization_header()

    assert header == {"Authorization": "Bearer a1"}
    assert provider.login_calls == 1


async def test_valid_token_is_reused_without_new_login() -> None:
    provider = FakeTokenProvider([_token("a1", expires_in_min=60)])
    client = AuthClient(provider, now=MovableClock(_NOW))

    await client.authorization_header()
    await client.authorization_header()

    assert provider.login_calls == 1
    assert provider.refresh_calls == 0


async def test_refreshes_when_token_is_near_expiry() -> None:
    provider = FakeTokenProvider([_token("a1", expires_in_min=60)])
    provider.refresh_result = _token("a2", expires_in_min=120, refresh="r2")
    clock = MovableClock(_NOW)
    client = AuthClient(provider, now=clock, refresh_margin=timedelta(minutes=5))

    await client.authorization_header()
    clock.now = _NOW + timedelta(minutes=56)  # 4 min to expiry, inside margin
    header = await client.authorization_header()

    assert header == {"Authorization": "Bearer a2"}
    assert provider.login_calls == 1
    assert provider.refresh_calls == 1


async def test_relogs_in_when_refresh_fails() -> None:
    provider = FakeTokenProvider(
        [_token("a1", expires_in_min=60), _token("a3", expires_in_min=60)]
    )
    provider.refresh_should_fail = True
    clock = MovableClock(_NOW)
    client = AuthClient(provider, now=clock)

    await client.authorization_header()
    clock.now = _NOW + timedelta(minutes=56)
    header = await client.authorization_header()

    assert header == {"Authorization": "Bearer a3"}
    assert provider.refresh_calls == 1
    assert provider.login_calls == 2


# ── parse_expiration (robust .NET DateTime handling) ───────────────


def test_parse_expiration_handles_utc_z_suffix() -> None:
    parsed = parse_expiration("2026-06-03T12:00:00Z")
    assert parsed == datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_expiration_truncates_seven_digit_fraction() -> None:
    # System.Text.Json emits up to 7 fractional digits (ticks).
    parsed = parse_expiration("2026-06-03T12:00:00.1234567Z")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.hour == 12


def test_parse_expiration_handles_explicit_offset() -> None:
    parsed = parse_expiration("2026-06-03T09:00:00-03:00")
    assert parsed == datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


# ── HttpTokenProvider (real HTTP shape, mocked transport) ──────────


class FakeAuthApi:
    """Named fake of the auth MS, served through httpx.MockTransport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.login_status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/auth/login":
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={"message": "nope"})
            return httpx.Response(200, json=self._auth_response("login-access"))
        if request.url.path == "/api/auth/refresh":
            return httpx.Response(200, json=self._auth_response("refresh-access"))
        return httpx.Response(404)

    @staticmethod
    def _auth_response(access: str) -> dict[str, object]:
        return {
            "accessToken": access,
            "refreshToken": "refresh-token",
            "expiration": "2026-06-03T13:00:00Z",
            "username": "me",
            "role": "USER",
        }


def _provider_with(api: FakeAuthApi) -> HttpTokenProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(api.handle))
    return HttpTokenProvider(
        base_url="https://example.com",
        email="me@example.com",
        password="s3cret",
        client=client,
    )


async def test_http_login_posts_credentials_and_parses_tokens() -> None:
    api = FakeAuthApi()
    provider = _provider_with(api)

    tokens = await provider.login()

    sent = api.requests[0]
    assert str(sent.url) == "https://example.com/api/auth/login"
    assert tokens.access_token == "login-access"
    assert tokens.refresh_token == "refresh-token"
    assert tokens.expires_at == datetime(2026, 6, 3, 13, 0, 0, tzinfo=timezone.utc)


async def test_http_refresh_sends_access_and_refresh_tokens() -> None:
    api = FakeAuthApi()
    provider = _provider_with(api)
    stale = TokenSet("old-access", "old-refresh", _NOW)

    tokens = await provider.refresh(stale)

    sent = api.requests[0]
    assert sent.url.path == "/api/auth/refresh"
    import json

    body = json.loads(sent.content)
    assert body == {"accessToken": "old-access", "refreshToken": "old-refresh"}
    assert tokens.access_token == "refresh-access"


async def test_http_login_raises_login_error_on_401() -> None:
    api = FakeAuthApi()
    api.login_status = 401
    provider = _provider_with(api)

    with pytest.raises(LoginError):
        await provider.login()
