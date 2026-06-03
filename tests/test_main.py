"""Tests for the Telegram handlers and allowlist guard in bot.main."""

from bot.main import authorized_only, echo_message, start_command, verify_login
from bot.security import Allowlist
from tests.test_auth_client import FakeTokenProvider, _token
from bot.auth_client import AuthClient


class FakeUser:
    def __init__(self, user_id: int | None) -> None:
        self.id = user_id


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, user: FakeUser | None, message: FakeMessage) -> None:
        self.effective_user = user
        self.message = message


class RecordingHandler:
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, update: object, context: object) -> None:
        self.called = True


_ALLOWLIST = Allowlist(frozenset({111}))


async def test_guard_blocks_unauthorized_user() -> None:
    handler = RecordingHandler()
    guarded = authorized_only(_ALLOWLIST, handler)
    update = FakeUpdate(FakeUser(999), FakeMessage("hi"))

    await guarded(update, context=None)

    assert handler.called is False
    assert update.message.replies == []


async def test_guard_allows_authorized_user() -> None:
    handler = RecordingHandler()
    guarded = authorized_only(_ALLOWLIST, handler)
    update = FakeUpdate(FakeUser(111), FakeMessage("hi"))

    await guarded(update, context=None)

    assert handler.called is True


async def test_echo_replies_with_same_text() -> None:
    update = FakeUpdate(FakeUser(111), FakeMessage("oi mundo"))

    await echo_message(update, context=None)

    assert update.message.replies == ["oi mundo"]


async def test_start_command_sends_welcome() -> None:
    update = FakeUpdate(FakeUser(111), FakeMessage("/start"))

    await start_command(update, context=None)

    assert len(update.message.replies) == 1
    assert "BeanBalance" in update.message.replies[0]


async def test_verify_login_forces_a_login() -> None:
    provider = FakeTokenProvider([_token("a1", expires_in_min=60)])
    auth = AuthClient(provider)

    await verify_login(auth)

    assert provider.login_calls == 1
