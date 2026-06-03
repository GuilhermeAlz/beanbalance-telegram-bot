"""Tests for bot.api_client against a mocked BeanBalance API transport."""

import json
from decimal import Decimal

import httpx
import pytest

from bot.api_client import ApiError, BeanBalanceApiClient
from bot.models import Account, Budget, Category, Page, Transaction

_ACCOUNT = {"id": "acc-1", "name": "Nubank", "type": "CHECKING",
            "balance": 100.0, "createdAt": "x"}
_CATEGORY = {"id": "cat-1", "name": "Alimentação", "description": "d",
             "custom": True, "createdAt": "x"}
_TX = {"id": "tx-1", "amount": 11.60, "type": "EXPENSE", "description": "almoço",
       "date": "2026-06-03", "accountId": "acc-1", "accountName": "Nubank",
       "categoryId": "cat-1", "categoryName": "Alimentação", "createdAt": "x"}
_BUDGET = {"id": "b-1", "limitAmount": 500, "spentAmount": 120.5,
           "remainingAmount": 379.5, "referenceMonth": "2026-06",
           "categoryId": "cat-1", "categoryName": "Alimentação", "createdAt": "x"}
_PAGE = {"content": [_TX], "number": 0, "size": 20,
         "totalElements": 1, "totalPages": 1}


class FakeAuthorizer:
    def __init__(self) -> None:
        self.invalidated = 0

    async def authorization_header(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-token"}

    def invalidate(self) -> None:
        self.invalidated += 1


class FakeBeanBalanceApi:
    """Named fake of the Spring API served via httpx.MockTransport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.next_error: tuple[int, str] | None = None
        self.fail_first_get_accounts_401 = False
        self._account_gets = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next_error is not None:
            status, message = self.next_error
            return httpx.Response(status, json={"status": status, "message": message})
        return self._route(request)

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/api/accounts":
            if method == "GET":
                return self._maybe_401_then(self._collection(_ACCOUNT))
            return httpx.Response(201, json=_ACCOUNT)
        if path.startswith("/api/accounts/"):
            return self._item_or_delete(method, _ACCOUNT)
        if path == "/api/categories":
            return self._list_or_create(method, _CATEGORY)
        if path.startswith("/api/categories/"):
            return self._item_or_delete(method, _CATEGORY)
        if path == "/api/transactions":
            return httpx.Response(200, json=_PAGE) if method == "GET" else httpx.Response(201, json=_TX)
        if path.startswith("/api/transactions/"):
            return self._item_or_delete(method, _TX)
        if path == "/api/budgets":
            return self._list_or_create(method, _BUDGET)
        if path.startswith("/api/budgets/"):
            return self._item_or_delete(method, _BUDGET)
        return httpx.Response(404, json={"status": 404, "message": "rota desconhecida"})

    def _maybe_401_then(self, ok: httpx.Response) -> httpx.Response:
        if self.fail_first_get_accounts_401 and self._account_gets == 0:
            self._account_gets += 1
            return httpx.Response(401, json={"status": 401, "message": "token expirado"})
        return ok

    @staticmethod
    def _collection(item: dict) -> httpx.Response:
        return httpx.Response(200, json=[item])

    def _list_or_create(self, method: str, item: dict) -> httpx.Response:
        return self._collection(item) if method == "GET" else httpx.Response(201, json=item)

    @staticmethod
    def _item_or_delete(method: str, item: dict) -> httpx.Response:
        if method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=item)


def _make_client(api: FakeBeanBalanceApi) -> tuple[BeanBalanceApiClient, FakeAuthorizer]:
    authorizer = FakeAuthorizer()
    http = httpx.AsyncClient(transport=httpx.MockTransport(api.handle))
    client = BeanBalanceApiClient("https://example.com", http, authorizer)
    return client, authorizer


def _last(api: FakeBeanBalanceApi) -> httpx.Request:
    return api.requests[-1]


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ── Accounts ───────────────────────────────────────────────────────


async def test_list_accounts_returns_models_with_auth_header() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    accounts = await client.list_accounts()

    assert accounts == [Account.from_json(_ACCOUNT)]
    assert _last(api).method == "GET"
    assert _last(api).url.path == "/api/accounts"
    assert _last(api).headers["Authorization"] == "Bearer test-token"


async def test_get_account_hits_item_path() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    account = await client.get_account("acc-1")

    assert account.id == "acc-1"
    assert _last(api).url.path == "/api/accounts/acc-1"


async def test_create_account_posts_compact_body() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.create_account(name="Reserva", type="SAVINGS", balance=Decimal("100"))

    sent = _last(api)
    assert sent.method == "POST"
    assert _body(sent) == {"name": "Reserva", "type": "SAVINGS", "balance": "100"}


async def test_create_account_omits_absent_balance() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.create_account(name="Cash", type="CASH")

    assert _body(_last(api)) == {"name": "Cash", "type": "CASH"}


async def test_update_account_uses_put_on_item_path() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.update_account("acc-1", name="Novo", type="CHECKING")

    assert _last(api).method == "PUT"
    assert _last(api).url.path == "/api/accounts/acc-1"


async def test_delete_account_returns_none_on_204() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    result = await client.delete_account("acc-1")

    assert result is None
    assert _last(api).method == "DELETE"


# ── Categories ─────────────────────────────────────────────────────


async def test_list_categories_returns_models() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    categories = await client.list_categories()

    assert categories == [Category.from_json(_CATEGORY)]


async def test_create_category_posts_name_and_description() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.create_category(name="Saúde", description="médico")

    assert _body(_last(api)) == {"name": "Saúde", "description": "médico"}


async def test_update_category_uses_put() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.update_category("cat-1", name="Renomeada")

    assert _last(api).method == "PUT"
    assert _last(api).url.path == "/api/categories/cat-1"


async def test_delete_category_returns_none() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    assert await client.delete_category("cat-1") is None


# ── Transactions ───────────────────────────────────────────────────


async def test_list_transactions_returns_page_with_query_params() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    page = await client.list_transactions(page=2, size=10)

    assert isinstance(page, Page)
    assert page.content == [Transaction.from_json(_TX)]
    assert _last(api).url.params["page"] == "2"
    assert _last(api).url.params["size"] == "10"


async def test_get_transaction_hits_item_path() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    tx = await client.get_transaction("tx-1")

    assert tx.id == "tx-1"
    assert _last(api).url.path == "/api/transactions/tx-1"


async def test_create_transaction_serializes_amount_as_string() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.create_transaction(
        amount=Decimal("11.60"),
        type="EXPENSE",
        date="2026-06-03",
        account_id="acc-1",
        category_id="cat-1",
        description="almoço",
    )

    assert _body(_last(api)) == {
        "amount": "11.60",
        "type": "EXPENSE",
        "date": "2026-06-03",
        "accountId": "acc-1",
        "categoryId": "cat-1",
        "description": "almoço",
    }


async def test_delete_transaction_returns_none() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    assert await client.delete_transaction("tx-1") is None


# ── Budgets ────────────────────────────────────────────────────────


async def test_list_budgets_with_month_param() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    budgets = await client.list_budgets(month="2026-06")

    assert budgets == [Budget.from_json(_BUDGET)]
    assert _last(api).url.params["month"] == "2026-06"


async def test_list_budgets_without_month_sends_no_param() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.list_budgets()

    assert "month" not in _last(api).url.params


async def test_create_budget_posts_reference_month() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.create_budget(
        limit_amount=Decimal("500"), reference_month="2026-06", category_id="cat-1"
    )

    assert _body(_last(api)) == {
        "limitAmount": "500",
        "referenceMonth": "2026-06",
        "categoryId": "cat-1",
    }


async def test_update_budget_uses_put() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    await client.update_budget(
        "b-1", limit_amount=Decimal("600"), reference_month="2026-06", category_id="cat-1"
    )

    assert _last(api).method == "PUT"
    assert _last(api).url.path == "/api/budgets/b-1"


async def test_delete_budget_returns_none() -> None:
    api = FakeBeanBalanceApi()
    client, _ = _make_client(api)

    assert await client.delete_budget("b-1") is None


# ── Cross-cutting: refresh-on-401 and errors ───────────────────────


async def test_retries_once_after_401_invalidating_token() -> None:
    api = FakeBeanBalanceApi()
    api.fail_first_get_accounts_401 = True
    client, authorizer = _make_client(api)

    accounts = await client.list_accounts()

    assert accounts == [Account.from_json(_ACCOUNT)]
    assert authorizer.invalidated == 1
    assert len([r for r in api.requests if r.url.path == "/api/accounts"]) == 2


async def test_non_success_status_raises_api_error_with_message() -> None:
    api = FakeBeanBalanceApi()
    api.next_error = (404, "Conta não encontrada")
    client, _ = _make_client(api)

    with pytest.raises(ApiError) as caught:
        await client.get_account("missing")

    assert caught.value.status_code == 404
    assert "Conta não encontrada" in str(caught.value)
