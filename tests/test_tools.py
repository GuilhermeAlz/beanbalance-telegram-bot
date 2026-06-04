"""Tests for the Gemini function declarations in bot.tools."""

from google.genai import types

from bot.tools import FINANCE_TOOL, TOOL_DECLARATIONS, TOOL_NAMES

_EXPECTED_NAMES = {
    "listar_contas",
    "obter_conta",
    "criar_conta",
    "atualizar_conta",
    "excluir_conta",
    "listar_categorias",
    "criar_categoria",
    "atualizar_categoria",
    "excluir_categoria",
    "criar_transacao",
    "listar_transacoes",
    "excluir_transacao",
    "listar_orcamentos",
    "criar_orcamento",
    "atualizar_orcamento",
    "excluir_orcamento",
}


def _by_name(name: str) -> types.FunctionDeclaration:
    return next(d for d in TOOL_DECLARATIONS if d.name == name)


def test_declares_all_sixteen_tools_without_duplicates() -> None:
    names = [d.name for d in TOOL_DECLARATIONS]

    assert len(names) == 16
    assert set(names) == _EXPECTED_NAMES
    assert len(set(names)) == len(names)


def test_tool_names_set_matches_declarations() -> None:
    assert TOOL_NAMES == _EXPECTED_NAMES


def test_finance_tool_wraps_all_declarations() -> None:
    assert isinstance(FINANCE_TOOL, types.Tool)
    assert FINANCE_TOOL.function_declarations is not None
    assert len(FINANCE_TOOL.function_declarations) == 16


def test_every_declaration_has_a_portuguese_description() -> None:
    for decl in TOOL_DECLARATIONS:
        assert decl.description
        assert len(decl.description) > 10


def test_criar_transacao_requires_amount_type_and_ids_but_not_date() -> None:
    params = _by_name("criar_transacao").parameters

    assert set(params.required) == {"amount", "type", "accountId", "categoryId"}
    # date is optional: the executor fills today when the user omits it.
    assert "date" not in params.required
    assert "date" in params.properties
    assert "description" in params.properties
    assert "description" not in params.required


def test_criar_transacao_type_is_constrained_to_income_or_expense() -> None:
    props = _by_name("criar_transacao").parameters.properties

    assert set(props["type"].enum) == {"INCOME", "EXPENSE"}
    assert props["amount"].type == types.Type.NUMBER


def test_criar_conta_type_lists_all_account_types() -> None:
    props = _by_name("criar_conta").parameters.properties

    assert set(props["type"].enum) == {
        "CHECKING",
        "SAVINGS",
        "CREDIT_CARD",
        "INVESTMENT",
        "CASH",
    }


def test_obter_conta_requires_account_id() -> None:
    params = _by_name("obter_conta").parameters

    assert params.required == ["accountId"]


def test_criar_orcamento_requires_limit_reference_month_and_category() -> None:
    params = _by_name("criar_orcamento").parameters

    assert set(params.required) == {"limitAmount", "referenceMonth", "categoryId"}


def test_read_only_listings_take_no_required_args() -> None:
    for name in ("listar_contas", "listar_categorias"):
        params = _by_name(name).parameters
        assert not params.required
