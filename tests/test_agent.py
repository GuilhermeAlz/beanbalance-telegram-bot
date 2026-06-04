"""Tests for the agentic loop and conversation memory in bot.agent."""

from decimal import Decimal
from typing import Any

from google.genai import types

from bot.agent import Agent, GeminiClient, LlmTurn


def _text_turn(text: str) -> LlmTurn:
    content = types.Content(role="model", parts=[types.Part(text=text)])
    return LlmTurn(text=text, function_calls=[], content=content)


def _call_turn(*calls: tuple[str, dict]) -> LlmTurn:
    parts = [types.Part.from_function_call(name=n, args=a) for n, a in calls]
    fcs = [types.FunctionCall(name=n, args=a) for n, a in calls]
    content = types.Content(role="model", parts=parts)
    return LlmTurn(text=None, function_calls=fcs, content=content)


class FakeLlmClient:
    """Returns scripted turns and records the contents of each generate call."""

    def __init__(self, turns: list[LlmTurn], *, repeat: bool = False) -> None:
        self._turns = list(turns)
        self._repeat = repeat
        self.calls: list[list[types.Content]] = []

    async def generate(self, contents: list[types.Content]) -> LlmTurn:
        self.calls.append(list(contents))
        turn = self._turns[0]
        if not (self._repeat and len(self._turns) == 1):
            self._turns.pop(0)
        return turn


class FakeToolExecutor:
    """Records executed tool calls and returns canned results."""

    def __init__(self, results: dict[str, dict] | None = None) -> None:
        self.results = results or {}
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.executed.append((name, args))
        return self.results.get(name, {"ok": True})


def _agent(llm: FakeLlmClient, executor: FakeToolExecutor, **kw: Any) -> Agent:
    return Agent(llm, executor, **kw)


def _function_response_parts(content: types.Content) -> list[types.Part]:
    return [p for p in content.parts if p.function_response is not None]


# ── Basic loop ─────────────────────────────────────────────────────


async def test_plain_text_response_skips_tools() -> None:
    llm = FakeLlmClient([_text_turn("Olá!")])
    executor = FakeToolExecutor()
    agent = _agent(llm, executor)

    reply = await agent.handle(chat_id=1, message="oi")

    assert reply == "Olá!"
    assert executor.executed == []


async def test_executes_tool_then_returns_followup_text() -> None:
    llm = FakeLlmClient([
        _call_turn(("listar_contas", {})),
        _text_turn("Você tem 1 conta."),
    ])
    executor = FakeToolExecutor({"listar_contas": {"contas": []}})
    agent = _agent(llm, executor)

    reply = await agent.handle(chat_id=1, message="quais minhas contas?")

    assert reply == "Você tem 1 conta."
    assert executor.executed == [("listar_contas", {})]


async def test_threads_function_response_into_next_generate_call() -> None:
    llm = FakeLlmClient([
        _call_turn(("listar_contas", {})),
        _text_turn("pronto"),
    ])
    executor = FakeToolExecutor({"listar_contas": {"contas": [{"id": "acc-1"}]}})
    agent = _agent(llm, executor)

    await agent.handle(chat_id=1, message="x")

    # The second generate must see: user msg, model tool-call turn, tool response.
    second_call_contents = llm.calls[1]
    response_parts = _function_response_parts(second_call_contents[-1])
    assert len(response_parts) == 1
    assert response_parts[0].function_response.name == "listar_contas"
    assert response_parts[0].function_response.response == {"contas": [{"id": "acc-1"}]}


async def test_runs_multiple_tool_calls_from_one_turn() -> None:
    llm = FakeLlmClient([
        _call_turn(("listar_contas", {}), ("listar_categorias", {})),
        _text_turn("ok"),
    ])
    executor = FakeToolExecutor()
    agent = _agent(llm, executor)

    await agent.handle(chat_id=1, message="x")

    assert executor.executed == [("listar_contas", {}), ("listar_categorias", {})]
    response_parts = _function_response_parts(llm.calls[1][-1])
    assert len(response_parts) == 2


async def test_stops_after_max_iterations_with_fallback_message() -> None:
    llm = FakeLlmClient([_call_turn(("listar_contas", {}))], repeat=True)
    executor = FakeToolExecutor()
    agent = _agent(llm, executor, max_tool_iterations=3)

    reply = await agent.handle(chat_id=1, message="x")

    assert len(llm.calls) == 3
    assert len(executor.executed) == 3
    assert "não consegui" in reply.lower()


# ── Conversation memory ────────────────────────────────────────────


async def test_memory_carries_previous_exchange_into_next_message() -> None:
    llm = FakeLlmClient([_text_turn("primeira"), _text_turn("segunda")])
    agent = _agent(llm, FakeToolExecutor())

    await agent.handle(chat_id=7, message="msg um")
    await agent.handle(chat_id=7, message="msg dois")

    second_contents = llm.calls[1]
    texts = [p.text for c in second_contents for p in c.parts if p.text]
    assert "msg um" in texts
    assert "primeira" in texts
    assert "msg dois" in texts


async def test_memory_is_isolated_per_chat() -> None:
    llm = FakeLlmClient([_text_turn("a"), _text_turn("b")])
    agent = _agent(llm, FakeToolExecutor())

    await agent.handle(chat_id=1, message="do chat 1")
    await agent.handle(chat_id=2, message="do chat 2")

    second_contents = llm.calls[1]
    texts = [p.text for c in second_contents for p in c.parts if p.text]
    assert "do chat 1" not in texts
    assert "do chat 2" in texts


async def test_memory_is_trimmed_to_configured_size() -> None:
    llm = FakeLlmClient([_text_turn(f"r{i}") for i in range(5)])
    agent = _agent(llm, FakeToolExecutor(), memory_size=2)

    for i in range(5):
        await agent.handle(chat_id=1, message=f"m{i}")

    # The 5th call should only carry the trimmed history (2 messages) + new msg.
    fifth_contents = llm.calls[4]
    assert len(fifth_contents) == 2 + 1


async def test_reset_clears_history_for_chat() -> None:
    llm = FakeLlmClient([_text_turn("um"), _text_turn("dois")])
    agent = _agent(llm, FakeToolExecutor())

    await agent.handle(chat_id=1, message="primeira")
    agent.reset(chat_id=1)
    await agent.handle(chat_id=1, message="nova")

    second_contents = llm.calls[1]
    assert len(second_contents) == 1  # only the new user message, no history


# ── Real Gemini adapter ────────────────────────────────────────────


class FakeSdkResponse:
    def __init__(self, text: str | None, function_calls: list, content: types.Content) -> None:
        self.text = text
        self.function_calls = function_calls
        self.candidates = [type("C", (), {"content": content})()]


class FakeGenerateContent:
    def __init__(self, response: FakeSdkResponse) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def __call__(self, **kwargs: Any) -> FakeSdkResponse:
        self.kwargs = kwargs
        return self.response


async def test_agent_with_real_executor_creates_transaction_end_to_end() -> None:
    """Plan's multi-step scenario: resolve account+category, then create tx."""
    from bot.tool_executor import ToolExecutor
    from tests.test_tool_executor import FakeApiClient

    api = FakeApiClient()
    executor = ToolExecutor(api)
    llm = FakeLlmClient([
        _call_turn(("listar_contas", {}), ("listar_categorias", {})),
        _call_turn(("criar_transacao", {
            "amount": 11.60, "type": "EXPENSE", "date": "2026-06-03",
            "accountId": "acc-1", "categoryId": "cat-1"})),
        _text_turn("✅ Registrei R$ 11,60 de Alimentação no Nubank."),
    ])
    agent = Agent(llm, executor)

    reply = await agent.handle(chat_id=1, message="gastei 11,60 de alimentação no nubank")

    assert "Registrei" in reply
    created = [c for c in api.calls if c[0] == "create_transaction"]
    assert created and created[0][1]["amount"] == Decimal("11.6")
    # The function responses threaded back must be JSON-serializable for the SDK.
    import json
    for content in llm.calls[2]:
        for part in content.parts:
            if part.function_response is not None:
                json.dumps(part.function_response.response)


async def test_gemini_client_maps_sdk_response_to_llm_turn() -> None:
    content = types.Content(role="model", parts=[types.Part(text="oi")])
    response = FakeSdkResponse("oi", [], content)
    generate = FakeGenerateContent(response)
    client = GeminiClient(
        generate_content=generate, model="gemini-2.5-pro",
        system_instruction="sys", tools=[],
    )

    turn = await client.generate([types.Content(role="user", parts=[types.Part(text="x")])])

    assert turn.text == "oi"
    assert turn.content is content
    assert generate.kwargs["model"] == "gemini-2.5-pro"
    assert generate.kwargs["config"].system_instruction == "sys"
