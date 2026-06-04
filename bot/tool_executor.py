"""Dispatches Gemini tool calls to the BeanBalance API client.

Each tool name declared in bot.tools maps to one handler here. Handlers pull
arguments out of the LLM-provided dict (numbers arrive as float/int, so money is
re-parsed through Decimal to stay exact), call the typed api_client, and return a
plain JSON-serializable dict to hand back to the model as the function response.

Errors never propagate: an ApiError or a missing argument becomes an ``{"erro":
...}`` result so the model can explain the failure to the user in natural
language instead of the loop crashing.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from bot.api_client import ApiError
from bot.models import Account, Budget, Category, Page, Transaction

# The user is in Brazil; pin "today" to São Paulo so a transaction registered
# near midnight does not land on the wrong calendar day (server may run in UTC).
_LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def _default_now() -> datetime:
    return datetime.now(_LOCAL_TZ)


class FinanceApi(Protocol):
    """The subset of BeanBalanceApiClient the executor depends on."""

    async def list_accounts(self) -> list[Account]: ...
    async def get_account(self, account_id: str) -> Account: ...
    async def create_account(self, *, name: str, type: str,
                             balance: Decimal | None = None) -> Account: ...
    async def update_account(self, account_id: str, *, name: str, type: str,
                             balance: Decimal | None = None) -> Account: ...
    async def delete_account(self, account_id: str) -> None: ...
    async def list_categories(self) -> list[Category]: ...
    async def create_category(self, *, name: str,
                              description: str | None = None) -> Category: ...
    async def update_category(self, category_id: str, *, name: str,
                              description: str | None = None) -> Category: ...
    async def delete_category(self, category_id: str) -> None: ...
    async def list_transactions(self, *, page: int = 0, size: int = 20) -> Page: ...
    async def create_transaction(self, *, amount: Decimal, type: str, date: str,
                                 account_id: str, category_id: str,
                                 description: str | None = None) -> Transaction: ...
    async def delete_transaction(self, transaction_id: str) -> None: ...
    async def list_budgets(self, *, month: str | None = None) -> list[Budget]: ...
    async def create_budget(self, *, limit_amount: Decimal, reference_month: str,
                            category_id: str) -> Budget: ...
    async def update_budget(self, budget_id: str, *, limit_amount: Decimal,
                            reference_month: str, category_id: str) -> Budget: ...
    async def delete_budget(self, budget_id: str) -> None: ...


Handler = Callable[[FinanceApi, dict[str, Any]], Awaitable[dict[str, Any]]]

_OK = {"sucesso": True}


class ToolExecutor:
    def __init__(
        self, api: FinanceApi, *, now: Callable[[], datetime] = _default_now
    ) -> None:
        self._api = api
        self._now = now

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = _HANDLERS.get(name)
        if handler is None:
            return {"erro": f"Ferramenta desconhecida: {name}"}
        args = self._apply_defaults(name, args)
        try:
            return await handler(self._api, args)
        except ApiError as error:
            return {"erro": error.message}
        except KeyError as missing:
            return {"erro": f"Argumento obrigatório ausente: {missing.args[0]}"}
        except (InvalidOperation, ValueError) as bad:
            return {"erro": f"Argumento inválido: {bad}"}

    def _apply_defaults(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Fills the transaction date with today when the model omitted it.

        The LLM has no clock, so an unspecified date would otherwise be an
        invented (usually past) value. Defaulting here guarantees the current
        date while still honoring an explicit date the user asked for.
        """
        if name == "criar_transacao" and not args.get("date"):
            return {**args, "date": self._now().strftime("%Y-%m-%d")}
        return args


# Argument coercion


def _money(value: Any) -> Decimal:
    return Decimal(str(value))


def _opt_money(value: Any) -> Decimal | None:
    return None if value is None else _money(value)


# Model serialization (model → camelCase JSON dict)


def _account_dict(a: Account) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "type": a.type,
            "balance": None if a.balance is None else str(a.balance),
            "createdAt": a.created_at}


def _category_dict(c: Category) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "description": c.description,
            "custom": c.custom, "createdAt": c.created_at}


def _transaction_dict(t: Transaction) -> dict[str, Any]:
    return {"id": t.id, "amount": str(t.amount), "type": t.type,
            "description": t.description, "date": t.date,
            "accountId": t.account_id, "accountName": t.account_name,
            "categoryId": t.category_id, "categoryName": t.category_name,
            "createdAt": t.created_at}


def _budget_dict(b: Budget) -> dict[str, Any]:
    return {"id": b.id, "limitAmount": str(b.limit_amount),
            "spentAmount": str(b.spent_amount),
            "remainingAmount": str(b.remaining_amount),
            "referenceMonth": b.reference_month, "categoryId": b.category_id,
            "categoryName": b.category_name, "createdAt": b.created_at}


# Handlers


async def _listar_contas(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    return {"contas": [_account_dict(a) for a in await api.list_accounts()]}


async def _obter_conta(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    return {"conta": _account_dict(await api.get_account(args["accountId"]))}


async def _criar_conta(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    account = await api.create_account(
        name=args["name"], type=args["type"],
        balance=_opt_money(args.get("balance")))
    return {"conta": _account_dict(account)}


async def _atualizar_conta(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    account = await api.update_account(
        args["accountId"], name=args["name"], type=args["type"],
        balance=_opt_money(args.get("balance")))
    return {"conta": _account_dict(account)}


async def _excluir_conta(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    await api.delete_account(args["accountId"])
    return _OK


async def _listar_categorias(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    return {"categorias": [_category_dict(c) for c in await api.list_categories()]}


async def _criar_categoria(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    category = await api.create_category(
        name=args["name"], description=args.get("description"))
    return {"categoria": _category_dict(category)}


async def _atualizar_categoria(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    category = await api.update_category(
        args["categoryId"], name=args["name"], description=args.get("description"))
    return {"categoria": _category_dict(category)}


async def _excluir_categoria(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    await api.delete_category(args["categoryId"])
    return _OK


async def _criar_transacao(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    tx = await api.create_transaction(
        amount=_money(args["amount"]), type=args["type"], date=args["date"],
        account_id=args["accountId"], category_id=args["categoryId"],
        description=args.get("description"))
    return {"transacao": _transaction_dict(tx)}


async def _listar_transacoes(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    page = await api.list_transactions(
        page=int(args.get("page", 0)), size=int(args.get("size", 20)))
    return {
        "transacoes": [_transaction_dict(t) for t in page.content],
        "pagina": page.number,
        "totalPaginas": page.total_pages,
        "totalElements": page.total_elements,
    }


async def _excluir_transacao(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    await api.delete_transaction(args["transactionId"])
    return _OK


async def _listar_orcamentos(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    budgets = await api.list_budgets(month=args.get("month"))
    return {"orcamentos": [_budget_dict(b) for b in budgets]}


async def _criar_orcamento(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    budget = await api.create_budget(
        limit_amount=_money(args["limitAmount"]),
        reference_month=args["referenceMonth"], category_id=args["categoryId"])
    return {"orcamento": _budget_dict(budget)}


async def _atualizar_orcamento(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    budget = await api.update_budget(
        args["budgetId"], limit_amount=_money(args["limitAmount"]),
        reference_month=args["referenceMonth"], category_id=args["categoryId"])
    return {"orcamento": _budget_dict(budget)}


async def _excluir_orcamento(api: FinanceApi, args: dict[str, Any]) -> dict[str, Any]:
    await api.delete_budget(args["budgetId"])
    return _OK


_HANDLERS: dict[str, Handler] = {
    "listar_contas": _listar_contas,
    "obter_conta": _obter_conta,
    "criar_conta": _criar_conta,
    "atualizar_conta": _atualizar_conta,
    "excluir_conta": _excluir_conta,
    "listar_categorias": _listar_categorias,
    "criar_categoria": _criar_categoria,
    "atualizar_categoria": _atualizar_categoria,
    "excluir_categoria": _excluir_categoria,
    "criar_transacao": _criar_transacao,
    "listar_transacoes": _listar_transacoes,
    "excluir_transacao": _excluir_transacao,
    "listar_orcamentos": _listar_orcamentos,
    "criar_orcamento": _criar_orcamento,
    "atualizar_orcamento": _atualizar_orcamento,
    "excluir_orcamento": _excluir_orcamento,
}
