"""Typed domain models mirroring the BeanBalance API responses.

Money fields are kept as Decimal (the API serializes Java BigDecimal as JSON
numbers); parse the HTTP body with Decimal to avoid float rounding.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    type: str
    balance: Decimal | None
    created_at: str

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Account":
        return Account(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            balance=_to_decimal(data.get("balance")),
            created_at=data["createdAt"],
        )


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str | None
    custom: bool
    created_at: str

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Category":
        return Category(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            custom=bool(data["custom"]),
            created_at=data["createdAt"],
        )


@dataclass(frozen=True)
class Transaction:
    id: str
    amount: Decimal
    type: str
    description: str | None
    date: str
    account_id: str
    account_name: str
    category_id: str
    category_name: str
    created_at: str

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Transaction":
        return Transaction(
            id=data["id"],
            amount=Decimal(str(data["amount"])),
            type=data["type"],
            description=data.get("description"),
            date=data["date"],
            account_id=data["accountId"],
            account_name=data["accountName"],
            category_id=data["categoryId"],
            category_name=data["categoryName"],
            created_at=data["createdAt"],
        )


@dataclass(frozen=True)
class Budget:
    id: str
    limit_amount: Decimal
    spent_amount: Decimal
    remaining_amount: Decimal
    reference_month: str
    category_id: str
    category_name: str
    created_at: str

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Budget":
        return Budget(
            id=data["id"],
            limit_amount=Decimal(str(data["limitAmount"])),
            spent_amount=Decimal(str(data["spentAmount"])),
            remaining_amount=Decimal(str(data["remainingAmount"])),
            reference_month=data["referenceMonth"],
            category_id=data["categoryId"],
            category_name=data["categoryName"],
            created_at=data["createdAt"],
        )


@dataclass(frozen=True)
class Page(Generic[T]):
    """A slice of a Spring Data Page response."""

    content: list[T]
    number: int
    size: int
    total_elements: int
    total_pages: int

    @staticmethod
    def from_json(data: dict[str, Any], item: Callable[[dict[str, Any]], T]) -> "Page[T]":
        return Page(
            content=[item(row) for row in data["content"]],
            number=data["number"],
            size=data["size"],
            total_elements=data["totalElements"],
            total_pages=data["totalPages"],
        )
