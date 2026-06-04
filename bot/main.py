"""Telegram entry point: polling bot backed by the Gemini agent.

The bot runs, enforces the allowlist, logs in to BeanBalance at startup, and
routes free-text messages through the agentic loop (Gemini + finance tools).
Commands: /start, /help, /reset.

Run: python -m bot.main
"""

import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.agent import SYSTEM_PROMPT, Agent, GeminiClient
from bot.api_client import BeanBalanceApiClient
from bot.auth_client import AuthClient, HttpTokenProvider
from bot.config import BotConfig, ConfigError, load_config
from bot.security import Allowlist
from bot.tool_executor import ToolExecutor
from bot.tools import FINANCE_TOOL

logger = logging.getLogger("beanbalance_bot")

_WELCOME = (
    "Olá! Sou o BeanBalance Bot, seu assistente financeiro. "
    "Fale comigo em português: posso registrar despesas e receitas, consultar "
    "suas contas, categorias e orçamentos. Ex.: \"gastei 30 de mercado no Nubank\". "
    "Use /help para ver exemplos e /reset para limpar a conversa."
)

_HELP = (
    "Comandos:\n"
    "/start — apresentação\n"
    "/help — esta ajuda\n"
    "/reset — limpa o histórico da conversa\n\n"
    "Exemplos do que você pode pedir:\n"
    "• \"quanto tenho em cada conta?\"\n"
    "• \"gastei 11,60 de alimentação no Nubank hoje\" (diga se é despesa ou receita)\n"
    "• \"quais categorias eu tenho?\"\n"
    "• \"quanto já gastei do orçamento de alimentação em junho?\""
)

TelegramHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


class Conversation(Protocol):
    async def handle(self, chat_id: int, message: str) -> str: ...

    def reset(self, chat_id: int) -> None: ...


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_WELCOME)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP)


def agent_message(agent: Conversation) -> TelegramHandler:
    """Routes a free-text message through the agent and replies with its answer."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await agent.handle(update.effective_chat.id, update.message.text)
        await update.message.reply_text(reply)

    return handler


def reset_command(agent: Conversation) -> TelegramHandler:
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        agent.reset(update.effective_chat.id)
        await update.message.reply_text("Conversa reiniciada. 🧹")

    return handler


def authorized_only(allowlist: Allowlist, handler: TelegramHandler) -> TelegramHandler:
    """Wraps a handler so only allowlisted users reach it; others are ignored."""

    async def guarded(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        user_id = user.id if user else None
        if not allowlist.is_authorized(user_id):
            logger.warning("ignoring unauthorized telegram user", extra={"user_id": user_id})
            return
        await handler(update, context)

    return guarded


async def verify_login(auth: AuthClient) -> None:
    """Forces a login at startup so misconfigured credentials fail fast."""
    await auth.authorization_header()
    logger.info("authenticated to BeanBalance")


def build_application(
    config: BotConfig, auth: AuthClient, allowlist: Allowlist, agent: Conversation
) -> Application:
    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_login_hook(auth))
        .build()
    )
    guard = lambda h: authorized_only(allowlist, h)  # noqa: E731
    app.add_handler(CommandHandler("start", guard(start_command)))
    app.add_handler(CommandHandler("help", guard(help_command)))
    app.add_handler(CommandHandler("reset", guard(reset_command(agent))))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            guard(agent_message(agent)),
        )
    )
    return app


def _login_hook(auth: AuthClient) -> Callable[[Application], Awaitable[None]]:
    async def hook(_application: Application) -> None:
        await verify_login(auth)

    return hook


def _build_auth(config: BotConfig, client: httpx.AsyncClient) -> AuthClient:
    provider = HttpTokenProvider(
        base_url=config.beanbalance_api_url,
        email=config.beanbalance_email,
        password=config.beanbalance_password,
        client=client,
    )
    return AuthClient(provider)


def _build_agent(config: BotConfig, auth: AuthClient, client: httpx.AsyncClient) -> Agent:
    api = BeanBalanceApiClient(config.beanbalance_api_url, client, auth)
    executor = ToolExecutor(api)
    genai_client = genai.Client(api_key=config.gemini_api_key)
    llm = GeminiClient(
        generate_content=genai_client.aio.models.generate_content,
        model=config.gemini_model,
        system_instruction=SYSTEM_PROMPT,
        tools=[FINANCE_TOOL],
    )
    return Agent(llm, executor, memory_size=config.conversation_memory_size)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        user_id = getattr(record, "user_id", None)
        if user_id is not None:
            payload["user_id"] = user_id
        return json.dumps(payload)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main() -> None:
    _configure_logging()
    load_dotenv()
    try:
        config = load_config(os.environ)
    except ConfigError as exc:
        logger.error("invalid configuration: %s", exc)
        sys.exit(1)

    client = httpx.AsyncClient(timeout=30.0)
    auth = _build_auth(config, client)
    agent = _build_agent(config, auth, client)
    allowlist = Allowlist(config.allowed_telegram_ids)
    app = build_application(config, auth, allowlist, agent)
    logger.info("starting telegram polling")
    app.run_polling()


if __name__ == "__main__":
    main()
