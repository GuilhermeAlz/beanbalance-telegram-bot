"""Typed async client for the BeanBalance Finance API.

Each method maps to one REST endpoint, injects the Bearer header from an
Authorizer, and parses responses into the models in bot.models. On a 401 the
token is invalidated and the request is retried once (the auth MS token may
have been revoked even though it had not yet expired locally).

Usage:
    client = BeanBalanceApiClient(base_url, httpx.AsyncClient(), auth)
    accounts = await client.list_accounts()
"""

import json
from decimal import Decimal
from typing import Any, Protocol

import httpx

from bot.models import Account, Budget, Category, Page, Transaction


class Authorizer(Protocol):
    """Supplies auth headers and can drop cached tokens (see AuthClient)."""

    async def authorization_header(self) -> dict[str, str]: ...

    def invalidate(self) -> None: ...


class ApiError(Exception):
    """Raised when the API returns a non-success, non-204 status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"BeanBalance API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


Money = Decimal


class BeanBalanceApiClient:
    def __init__(
        self, base_url: str, client: httpx.AsyncClient, authorizer: Authorizer
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._authorizer = authorizer

    # Accounts

    async def list_accounts(self) -> list[Account]:
        rows = await self._request("GET", "/api/accounts")
        return [Account.from_json(row) for row in rows]

    async def get_account(self, account_id: str) -> Account:
        return Account.from_json(await self._request("GET", f"/api/accounts/{account_id}"))

    async def create_account(
        self, *, name: str, type: str, balance: Money | None = None
    ) -> Account:
        body = _compact({"name": name, "type": type, "balance": _money(balance)})
        return Account.from_json(await self._request("POST", "/api/accounts", json=body))

    async def update_account(
        self, account_id: str, *, name: str, type: str, balance: Money | None = None
    ) -> Account:
        body = _compact({"name": name, "type": type, "balance": _money(balance)})
        return Account.from_json(
            await self._request("PUT", f"/api/accounts/{account_id}", json=body)
        )

    async def delete_account(self, account_id: str) -> None:
        await self._request("DELETE", f"/api/accounts/{account_id}")

    # Categories

    async def list_categories(self) -> list[Category]:
        rows = await self._request("GET", "/api/categories")
        return [Category.from_json(row) for row in rows]

    async def create_category(
        self, *, name: str, description: str | None = None
    ) -> Category:
        body = _compact({"name": name, "description": description})
        return Category.from_json(await self._request("POST", "/api/categories", json=body))

    async def update_category(
        self, category_id: str, *, name: str, description: str | None = None
    ) -> Category:
        body = _compact({"name": name, "description": description})
        return Category.from_json(
            await self._request("PUT", f"/api/categories/{category_id}", json=body)
        )

    async def delete_category(self, category_id: str) -> None:
        await self._request("DELETE", f"/api/categories/{category_id}")

    # Transactions

    async def list_transactions(self, *, page: int = 0, size: int = 20) -> Page[Transaction]:
        data = await self._request(
            "GET", "/api/transactions", params={"page": page, "size": size}
        )
        return Page.from_json(data, Transaction.from_json)

    async def get_transaction(self, transaction_id: str) -> Transaction:
        return Transaction.from_json(
            await self._request("GET", f"/api/transactions/{transaction_id}")
        )

    async def create_transaction(
        self,
        *,
        amount: Money,
        type: str,
        date: str,
        account_id: str,
        category_id: str,
        description: str | None = None,
    ) -> Transaction:
        body = _compact(
            {
                "amount": _money(amount),
                "type": type,
                "date": date,
                "accountId": account_id,
                "categoryId": category_id,
                "description": description,
            }
        )
        return Transaction.from_json(
            await self._request("POST", "/api/transactions", json=body)
        )

    async def delete_transaction(self, transaction_id: str) -> None:
        await self._request("DELETE", f"/api/transactions/{transaction_id}")

    # Budgets

    async def list_budgets(self, *, month: str | None = None) -> list[Budget]:
        params = _compact({"month": month})
        rows = await self._request("GET", "/api/budgets", params=params)
        return [Budget.from_json(row) for row in rows]

    async def create_budget(
        self, *, limit_amount: Money, reference_month: str, category_id: str
    ) -> Budget:
        body = {
            "limitAmount": _money(limit_amount),
            "referenceMonth": reference_month,
            "categoryId": category_id,
        }
        return Budget.from_json(await self._request("POST", "/api/budgets", json=body))

    async def update_budget(
        self, budget_id: str, *, limit_amount: Money, reference_month: str, category_id: str
    ) -> Budget:
        body = {
            "limitAmount": _money(limit_amount),
            "referenceMonth": reference_month,
            "categoryId": category_id,
        }
        return Budget.from_json(
            await self._request("PUT", f"/api/budgets/{budget_id}", json=body)
        )

    async def delete_budget(self, budget_id: str) -> None:
        await self._request("DELETE", f"/api/budgets/{budget_id}")

    # Internals

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._send(method, path, json, params)
        if response.status_code == 401:
            self._authorizer.invalidate()
            response = await self._send(method, path, json, params)
        return self._parse(response)

    async def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> httpx.Response:
        headers = await self._authorizer.authorization_header()
        return await self._client.request(
            method, f"{self._base_url}{path}", headers=headers, json=body, params=params
        )

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code == 204:
            return None
        if not response.is_success:
            raise ApiError(response.status_code, _error_message(response))
        # parse_float=Decimal preserves precision for money fields.
        return json.loads(response.text, parse_float=Decimal)


def _money(value: Money | None) -> str | None:
    """Serializes money as a string so the JVM parses exact BigDecimals."""
    if value is None:
        return None
    return str(Decimal(str(value)))


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    """Drops keys whose value is None so optional fields are simply omitted."""
    return {key: value for key, value in data.items() if value is not None}


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return response.text or response.reason_phrase
