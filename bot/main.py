"""Telegram entry point: polling bot that echoes text and authenticates.

Milestone 1 scope — the bot runs, enforces the allowlist, echoes messages,
and logs in to BeanBalance at startup (caching the JWT). The Gemini agent
arrives in later milestones.

Run: python -m bot.main
"""

import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.auth_client import AuthClient, HttpTokenProvider
from bot.config import BotConfig, ConfigError, load_config
from bot.security import Allowlist

logger = logging.getLogger("beanbalance_bot")

_WELCOME = (
    "Olá! Sou o BeanBalance Bot, seu assistente financeiro. "
    "Por enquanto eu apenas repito suas mensagens — em breve poderei "
    "registrar transações e consultar suas contas."
)

TelegramHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_WELCOME)


async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(update.message.text)


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
    config: BotConfig, auth: AuthClient, allowlist: Allowlist
) -> Application:
    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_login_hook(auth))
        .build()
    )
    app.add_handler(CommandHandler("start", authorized_only(allowlist, start_command)))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            authorized_only(allowlist, echo_message),
        )
    )
    return app


def _login_hook(auth: AuthClient) -> Callable[[Application], Awaitable[None]]:
    async def hook(_application: Application) -> None:
        await verify_login(auth)

    return hook


def _build_auth(config: BotConfig) -> AuthClient:
    client = httpx.AsyncClient(timeout=30.0)
    provider = HttpTokenProvider(
        base_url=config.beanbalance_api_url,
        email=config.beanbalance_email,
        password=config.beanbalance_password,
        client=client,
    )
    return AuthClient(provider)


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

    auth = _build_auth(config)
    allowlist = Allowlist(config.allowed_telegram_ids)
    app = build_application(config, auth, allowlist)
    logger.info("starting telegram polling")
    app.run_polling()


if __name__ == "__main__":
    main()
