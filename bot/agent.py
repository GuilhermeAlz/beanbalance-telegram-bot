"""The agentic loop: turns a user message into a reply using Gemini + tools.

Flow per message:
  1. Build contents = rolling chat history + the new user message.
  2. Ask the LLM. If it returns function calls, run each through the
     ToolExecutor, append the model turn and the function responses, and ask
     again — up to ``max_tool_iterations`` times to bound runaway loops.
  3. When the LLM returns text, that text is the reply.

The loop depends only on the ``LlmClient`` protocol (and a tool executor with an
``execute`` coroutine), so it is fully testable without the network. GeminiClient
is the thin production adapter over the google-genai async SDK.

Conversation memory is a per-chat rolling window of plain user/assistant text
turns (intermediate tool-call turns are not persisted), trimmed to
``memory_size`` messages.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from google.genai import types

SYSTEM_PROMPT = """\
Você é o BeanBalance Bot, um assistente financeiro pessoal. Você ajuda o usuário \
a gerenciar suas finanças através do aplicativo BeanBalance.

Regras:
1. Quando o usuário mencionar uma transação, SEMPRE resolva nomes de contas e \
categorias para seus UUIDs chamando listar_contas e listar_categorias primeiro.
2. O tipo da transação (EXPENSE ou INCOME) DEVE ser informado pelo usuário. \
Se ele não especificar, pergunte: "Essa transação é uma despesa ou receita?"
3. Se o usuário não informar a data, NÃO preencha o campo 'date' ao chamar \
criar_transacao — o sistema registra automaticamente com a data de hoje. \
Só informe 'date' quando o usuário mencionar uma data específica.
4. Responda sempre em português (pt-BR).
5. Seja conciso — isso é um chat, não um relatório.
6. Formate valores monetários como R$ X.XXX,XX (formato brasileiro).
7. Após criar uma transação, confirme com: valor, tipo (despesa/receita), \
categoria, conta e data.
8. Se um nome for ambíguo (ex.: múltiplas categorias parecidas), peça ao \
usuário para especificar.
9. NUNCA invente dados — sempre use chamadas de ferramentas para obter \
informações reais.
10. Máximo de 5 chamadas de ferramentas sequenciais por mensagem do usuário."""

_FALLBACK = (
    "Desculpe, não consegui completar a operação — foram necessárias chamadas "
    "demais. Pode reformular ou dividir o pedido?"
)


@dataclass
class LlmTurn:
    """One model response: free text and/or tool calls, plus the raw turn.

    ``content`` is the model's Content (role=model) to thread back into history
    so the next call sees the tool calls it asked for.
    """

    text: str | None
    function_calls: list[types.FunctionCall]
    content: types.Content


class LlmClient(Protocol):
    async def generate(self, contents: list[types.Content]) -> LlmTurn: ...


class ToolRunner(Protocol):
    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


class Agent:
    def __init__(
        self,
        llm: LlmClient,
        executor: ToolRunner,
        *,
        memory_size: int = 10,
        max_tool_iterations: int = 5,
    ) -> None:
        self._llm = llm
        self._executor = executor
        self._memory_size = memory_size
        self._max_iterations = max_tool_iterations
        self._histories: dict[int, list[types.Content]] = {}

    async def handle(self, chat_id: int, message: str) -> str:
        user_turn = _user_text(message)
        contents = [*self._histories.get(chat_id, []), user_turn]

        reply = await self._run_loop(contents)

        self._remember(chat_id, user_turn, _model_text(reply))
        return reply

    def reset(self, chat_id: int) -> None:
        self._histories.pop(chat_id, None)

    async def _run_loop(self, contents: list[types.Content]) -> str:
        for _ in range(self._max_iterations):
            turn = await self._llm.generate(contents)
            contents.append(turn.content)
            if not turn.function_calls:
                return turn.text or ""
            contents.append(await self._run_tools(turn.function_calls))
        return _FALLBACK

    async def _run_tools(self, calls: list[types.FunctionCall]) -> types.Content:
        parts = []
        for call in calls:
            result = await self._executor.execute(call.name, dict(call.args or {}))
            parts.append(types.Part.from_function_response(name=call.name, response=result))
        return types.Content(role="user", parts=parts)

    def _remember(
        self, chat_id: int, user_turn: types.Content, model_turn: types.Content
    ) -> None:
        history = [*self._histories.get(chat_id, []), user_turn, model_turn]
        self._histories[chat_id] = history[-self._memory_size:]


def _user_text(message: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=message)])


def _model_text(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


GenerateContent = Callable[..., Awaitable[Any]]


class GeminiClient:
    """Production adapter over google-genai's async generate_content.

    ``generate_content`` is injected (in production ``client.aio.models
    .generate_content``) so the adapter stays unit-testable.
    """

    def __init__(
        self,
        *,
        generate_content: GenerateContent,
        model: str,
        system_instruction: str,
        tools: list[types.Tool],
    ) -> None:
        self._generate_content = generate_content
        self._model = model
        self._config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            # We drive the tool loop ourselves; disable the SDK's auto-calling.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def generate(self, contents: list[types.Content]) -> LlmTurn:
        response = await self._generate_content(
            model=self._model, contents=contents, config=self._config
        )
        return LlmTurn(
            text=response.text,
            function_calls=list(response.function_calls or []),
            content=response.candidates[0].content,
        )
