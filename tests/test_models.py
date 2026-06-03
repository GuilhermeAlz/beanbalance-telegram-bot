"""Tests for JSON -> domain model mapping in bot.models."""

from decimal import Decimal

from bot.models import Account, Budget, Category, Page, Transaction


def test_account_from_json_keeps_money_as_decimal() -> None:
    account = Account.from_json(
        {
            "id": "acc-1",
            "name": "Nubank",
            "type": "CHECKING",
            "balance": 1234.56,
            "createdAt": "2026-06-01T10:00:00",
        }
    )

    assert account.id == "acc-1"
    assert account.name == "Nubank"
    assert account.type == "CHECKING"
    assert account.balance == Decimal("1234.56")


def test_account_balance_may_be_absent() -> None:
    account = Account.from_json(
        {"id": "a", "name": "Cash", "type": "CASH", "createdAt": "x"}
    )
    assert account.balance is None


def test_category_from_json_maps_custom_flag() -> None:
    category = Category.from_json(
        {
            "id": "cat-1",
            "name": "Alimentação",
            "description": "Comida",
            "custom": True,
            "createdAt": "x",
        }
    )
    assert category.id == "cat-1"
    assert category.custom is True


def test_transaction_from_json_maps_account_and_category_names() -> None:
    tx = Transaction.from_json(
        {
            "id": "tx-1",
            "amount": 11.60,
            "type": "EXPENSE",
            "description": "almoço",
            "date": "2026-06-03",
            "accountId": "acc-1",
            "accountName": "Nubank",
            "categoryId": "cat-1",
            "categoryName": "Alimentação",
            "createdAt": "x",
        }
    )
    assert tx.amount == Decimal("11.60")
    assert tx.type == "EXPENSE"
    assert tx.account_name == "Nubank"
    assert tx.category_name == "Alimentação"


def test_budget_from_json_maps_computed_amounts() -> None:
    budget = Budget.from_json(
        {
            "id": "b-1",
            "limitAmount": 500,
            "spentAmount": 120.50,
            "remainingAmount": 379.50,
            "referenceMonth": "2026-06",
            "categoryId": "cat-1",
            "categoryName": "Alimentação",
            "createdAt": "x",
        }
    )
    assert budget.limit_amount == Decimal("500")
    assert budget.spent_amount == Decimal("120.50")
    assert budget.remaining_amount == Decimal("379.50")
    assert budget.reference_month == "2026-06"


def test_page_from_json_maps_spring_page_envelope() -> None:
    page = Page.from_json(
        {
            "content": [
                {
                    "id": "tx-1",
                    "amount": 5,
                    "type": "INCOME",
                    "description": None,
                    "date": "2026-06-03",
                    "accountId": "a",
                    "accountName": "A",
                    "categoryId": "c",
                    "categoryName": "C",
                    "createdAt": "x",
                }
            ],
            "number": 0,
            "size": 20,
            "totalElements": 1,
            "totalPages": 1,
        },
        Transaction.from_json,
    )

    assert page.total_elements == 1
    assert page.total_pages == 1
    assert page.number == 0
    assert len(page.content) == 1
    assert page.content[0].amount == Decimal("5")
