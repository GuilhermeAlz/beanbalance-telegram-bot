"""Tests for the Telegram handlers and allowlist guard in bot.main."""

from bot.main import (
    agent_message,
    authorized_only,
    help_command,
    reset_command,
    start_command,
    verify_login,
)
from bot.security import Allowlist
from tests.test_auth_client import FakeTokenProvider, _token
from bot.auth_client import AuthClient


class FakeUser:
    def __init__(self, user_id: int | None) -> None:
        self.id = user_id


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeUpdate:
    def __init__(
        self, user: FakeUser | None, message: FakeMessage, chat_id: int = 1
    ) -> None:
        self.effective_user = user
        self.effective_chat = FakeChat(chat_id)
        self.message = message


class FakeAgent:
    def __init__(self, reply: str = "resposta do agente") -> None:
        self.reply = reply
        self.handled: list[tuple[int, str]] = []
        self.reset_calls: list[int] = []

    async def handle(self, chat_id: int, message: str) -> str:
        self.handled.append((chat_id, message))
        return self.reply

    def reset(self, chat_id: int) -> None:
        self.reset_calls.append(chat_id)


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


async def test_agent_message_replies_with_agent_output() -> None:
    agent = FakeAgent("Você tem 2 contas.")
    handler = agent_message(agent)
    update = FakeUpdate(FakeUser(111), FakeMessage("quais minhas contas?"), chat_id=42)

    await handler(update, context=None)

    assert agent.handled == [(42, "quais minhas contas?")]
    assert update.message.replies == ["Você tem 2 contas."]


async def test_reset_command_clears_history_and_confirms() -> None:
    agent = FakeAgent()
    handler = reset_command(agent)
    update = FakeUpdate(FakeUser(111), FakeMessage("/reset"), chat_id=42)

    await handler(update, context=None)

    assert agent.reset_calls == [42]
    assert len(update.message.replies) == 1


async def test_help_command_lists_usage_examples() -> None:
    update = FakeUpdate(FakeUser(111), FakeMessage("/help"))

    await help_command(update, context=None)

    assert len(update.message.replies) == 1
    assert update.message.replies[0]


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
