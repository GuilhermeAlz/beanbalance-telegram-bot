"""Tests for bot.tool_executor dispatching to a fake api_client."""

from datetime import datetime
from decimal import Decimal

import pytest

from bot.api_client import ApiError
from bot.models import Account, Budget, Category, Page, Transaction
from bot.tool_executor import ToolExecutor

_ACCOUNT = Account(id="acc-1", name="Nubank", type="CHECKING",
                   balance=Decimal("100.50"), created_at="x")
_CATEGORY = Category(id="cat-1", name="Alimentação", description="d",
                     custom=True, created_at="x")
_TX = Transaction(id="tx-1", amount=Decimal("11.60"), type="EXPENSE",
                  description="almoço", date="2026-06-03", account_id="acc-1",
                  account_name="Nubank", category_id="cat-1",
                  category_name="Alimentação", created_at="x")
_BUDGET = Budget(id="b-1", limit_amount=Decimal("500"), spent_amount=Decimal("120.50"),
                 remaining_amount=Decimal("379.50"), reference_month="2026-06",
                 category_id="cat-1", category_name="Alimentação", created_at="x")


class FakeApiClient:
    """Named fake of BeanBalanceApiClient recording the calls it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.error: ApiError | None = None

    def _record(self, op: str, **kwargs: object) -> None:
        self.calls.append((op, kwargs))
        if self.error is not None:
            raise self.error

    async def list_accounts(self) -> list[Account]:
        self._record("list_accounts")
        return [_ACCOUNT]

    async def get_account(self, account_id: str) -> Account:
        self._record("get_account", account_id=account_id)
        return _ACCOUNT

    async def create_account(self, *, name, type, balance=None) -> Account:
        self._record("create_account", name=name, type=type, balance=balance)
        return _ACCOUNT

    async def update_account(self, account_id, *, name, type, balance=None) -> Account:
        self._record("update_account", account_id=account_id, name=name,
                     type=type, balance=balance)
        return _ACCOUNT

    async def delete_account(self, account_id: str) -> None:
        self._record("delete_account", account_id=account_id)

    async def list_categories(self) -> list[Category]:
        self._record("list_categories")
        return [_CATEGORY]

    async def create_category(self, *, name, description=None) -> Category:
        self._record("create_category", name=name, description=description)
        return _CATEGORY

    async def update_category(self, category_id, *, name, description=None) -> Category:
        self._record("update_category", category_id=category_id, name=name,
                     description=description)
        return _CATEGORY

    async def delete_category(self, category_id: str) -> None:
        self._record("delete_category", category_id=category_id)

    async def list_transactions(self, *, page=0, size=20) -> Page:
        self._record("list_transactions", page=page, size=size)
        return Page(content=[_TX], number=page, size=size,
                    total_elements=1, total_pages=1)

    async def create_transaction(self, *, amount, type, date, account_id,
                                 category_id, description=None) -> Transaction:
        self._record("create_transaction", amount=amount, type=type, date=date,
                     account_id=account_id, category_id=category_id,
                     description=description)
        return _TX

    async def delete_transaction(self, transaction_id: str) -> None:
        self._record("delete_transaction", transaction_id=transaction_id)

    async def list_budgets(self, *, month=None) -> list[Budget]:
        self._record("list_budgets", month=month)
        return [_BUDGET]

    async def create_budget(self, *, limit_amount, reference_month, category_id) -> Budget:
        self._record("create_budget", limit_amount=limit_amount,
                     reference_month=reference_month, category_id=category_id)
        return _BUDGET

    async def update_budget(self, budget_id, *, limit_amount, reference_month,
                            category_id) -> Budget:
        self._record("update_budget", budget_id=budget_id, limit_amount=limit_amount,
                     reference_month=reference_month, category_id=category_id)
        return _BUDGET

    async def delete_budget(self, budget_id: str) -> None:
        self._record("delete_budget", budget_id=budget_id)


def _executor() -> tuple[ToolExecutor, FakeApiClient]:
    api = FakeApiClient()
    return ToolExecutor(api), api


def _last(api: FakeApiClient) -> tuple[str, dict]:
    return api.calls[-1]


# ── Reads ──────────────────────────────────────────────────────────


async def test_listar_contas_returns_serialized_accounts() -> None:
    executor, api = _executor()

    result = await executor.execute("listar_contas", {})

    assert _last(api)[0] == "list_accounts"
    assert result == {"contas": [{"id": "acc-1", "name": "Nubank",
                                  "type": "CHECKING", "balance": "100.50",
                                  "createdAt": "x"}]}


async def test_obter_conta_passes_account_id() -> None:
    executor, api = _executor()

    result = await executor.execute("obter_conta", {"accountId": "acc-1"})

    assert _last(api) == ("get_account", {"account_id": "acc-1"})
    assert result["conta"]["id"] == "acc-1"


async def test_listar_transacoes_returns_page_envelope() -> None:
    executor, api = _executor()

    result = await executor.execute("listar_transacoes", {"page": 1, "size": 5})

    assert _last(api) == ("list_transactions", {"page": 1, "size": 5})
    assert result["pagina"] == 1
    assert result["totalElements"] == 1
    assert result["transacoes"][0]["id"] == "tx-1"


async def test_listar_orcamentos_forwards_month() -> None:
    executor, api = _executor()

    await executor.execute("listar_orcamentos", {"month": "2026-06"})

    assert _last(api) == ("list_budgets", {"month": "2026-06"})


# ── Writes & money coercion ────────────────────────────────────────


def _fixed_now(date_str: str):
    moment = datetime.strptime(date_str, "%Y-%m-%d")
    return lambda: moment


async def test_criar_transacao_defaults_missing_date_to_today() -> None:
    api = FakeApiClient()
    executor = ToolExecutor(api, now=_fixed_now("2026-06-04"))

    await executor.execute(
        "criar_transacao",
        {"amount": 10, "type": "EXPENSE", "accountId": "acc-1", "categoryId": "cat-1"},
    )

    assert _last(api)[1]["date"] == "2026-06-04"


async def test_criar_transacao_treats_blank_date_as_today() -> None:
    api = FakeApiClient()
    executor = ToolExecutor(api, now=_fixed_now("2026-06-04"))

    await executor.execute(
        "criar_transacao",
        {"amount": 10, "type": "EXPENSE", "date": "",
         "accountId": "acc-1", "categoryId": "cat-1"},
    )

    assert _last(api)[1]["date"] == "2026-06-04"


async def test_criar_transacao_respects_explicit_date() -> None:
    api = FakeApiClient()
    executor = ToolExecutor(api, now=_fixed_now("2026-06-04"))

    await executor.execute(
        "criar_transacao",
        {"amount": 10, "type": "EXPENSE", "date": "2026-01-15",
         "accountId": "acc-1", "categoryId": "cat-1"},
    )

    assert _last(api)[1]["date"] == "2026-01-15"


async def test_criar_transacao_coerces_amount_to_decimal() -> None:
    executor, api = _executor()

    await executor.execute(
        "criar_transacao",
        {"amount": 11.60, "type": "EXPENSE", "date": "2026-06-03",
         "accountId": "acc-1", "categoryId": "cat-1", "description": "almoço"},
    )

    name, kwargs = _last(api)
    assert name == "create_transaction"
    assert kwargs["amount"] == Decimal("11.6")
    assert isinstance(kwargs["amount"], Decimal)
    assert kwargs["account_id"] == "acc-1"
    assert kwargs["category_id"] == "cat-1"


async def test_criar_conta_coerces_balance_and_keeps_it_optional() -> None:
    executor, api = _executor()

    await executor.execute("criar_conta", {"name": "Reserva", "type": "SAVINGS"})
    assert _last(api) == ("create_account",
                          {"name": "Reserva", "type": "SAVINGS", "balance": None})

    await executor.execute(
        "criar_conta", {"name": "R", "type": "SAVINGS", "balance": 50})
    assert _last(api)[1]["balance"] == Decimal("50")


async def test_criar_orcamento_maps_camel_case_args() -> None:
    executor, api = _executor()

    await executor.execute(
        "criar_orcamento",
        {"limitAmount": 500, "referenceMonth": "2026-06", "categoryId": "cat-1"},
    )

    name, kwargs = _last(api)
    assert name == "create_budget"
    assert kwargs == {"limit_amount": Decimal("500"),
                      "reference_month": "2026-06", "category_id": "cat-1"}


async def test_excluir_conta_returns_success_marker() -> None:
    executor, api = _executor()

    result = await executor.execute("excluir_conta", {"accountId": "acc-1"})

    assert _last(api) == ("delete_account", {"account_id": "acc-1"})
    assert result == {"sucesso": True}


# ── Error handling ─────────────────────────────────────────────────


async def test_api_error_becomes_friendly_result_not_exception() -> None:
    executor, api = _executor()
    api.error = ApiError(404, "Conta não encontrada")

    result = await executor.execute("obter_conta", {"accountId": "missing"})

    assert result == {"erro": "Conta não encontrada"}


async def test_unknown_tool_returns_error_result() -> None:
    executor, _ = _executor()

    result = await executor.execute("ferramenta_inexistente", {})

    assert "erro" in result
    assert "ferramenta_inexistente" in result["erro"]


async def test_missing_required_arg_returns_error_result() -> None:
    executor, _ = _executor()

    result = await executor.execute("obter_conta", {})

    assert "erro" in result
