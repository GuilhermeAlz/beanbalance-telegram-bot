"""Gemini function declarations for the BeanBalance finance tools.

These are the semantic tools the LLM may call. Names and descriptions are in
Portuguese (pt-BR) on purpose — the bot speaks Portuguese and the model reasons
better when the tool surface matches the conversation language.

The declarations are intentionally close to, but not 1:1 with, the REST API:
writing a transaction needs an accountId and categoryId, so the model is told to
resolve names to UUIDs via listar_contas / listar_categorias first.

bot.tool_executor maps each name here to a BeanBalanceApiClient call.
"""

from google.genai import types

_ACCOUNT_TYPES = ["CHECKING", "SAVINGS", "CREDIT_CARD", "INVESTMENT", "CASH"]
_TRANSACTION_TYPES = ["INCOME", "EXPENSE"]


def _obj(
    properties: dict[str, types.Schema], required: list[str] | None = None
) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties,
        required=required or [],
    )


def _str(description: str, *, enum: list[str] | None = None) -> types.Schema:
    return types.Schema(type=types.Type.STRING, description=description, enum=enum)


def _num(description: str) -> types.Schema:
    return types.Schema(type=types.Type.NUMBER, description=description)


def _decl(
    name: str, description: str, properties: dict[str, types.Schema] | None = None,
    required: list[str] | None = None,
) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=_obj(properties or {}, required),
    )


_ACCOUNT_ID = _str("UUID da conta (obtido via listar_contas)")
_CATEGORY_ID = _str("UUID da categoria (obtido via listar_categorias)")

TOOL_DECLARATIONS: list[types.FunctionDeclaration] = [
    # Contas
    _decl(
        "listar_contas",
        "Lista todas as contas financeiras do usuário com seus saldos. "
        "Use para responder 'quais são minhas contas' ou para resolver o nome "
        "de uma conta em seu UUID antes de registrar uma transação.",
    ),
    _decl(
        "obter_conta",
        "Busca os detalhes de uma conta específica pelo seu UUID.",
        {"accountId": _ACCOUNT_ID},
        ["accountId"],
    ),
    _decl(
        "criar_conta",
        "Cria uma nova conta financeira. O tipo deve ser um dos valores válidos.",
        {
            "name": _str("Nome da conta (ex.: Nubank, Carteira)"),
            "type": _str("Tipo da conta", enum=_ACCOUNT_TYPES),
            "balance": _num("Saldo inicial (opcional, número)"),
        },
        ["name", "type"],
    ),
    _decl(
        "atualizar_conta",
        "Atualiza o nome, tipo ou saldo de uma conta existente.",
        {
            "accountId": _ACCOUNT_ID,
            "name": _str("Novo nome da conta"),
            "type": _str("Novo tipo da conta", enum=_ACCOUNT_TYPES),
            "balance": _num("Novo saldo (opcional)"),
        },
        ["accountId", "name", "type"],
    ),
    _decl(
        "excluir_conta",
        "Exclui uma conta pelo seu UUID. Operação irreversível.",
        {"accountId": _ACCOUNT_ID},
        ["accountId"],
    ),
    # Categorias
    _decl(
        "listar_categorias",
        "Lista todas as categorias disponíveis. Use para resolver o nome de uma "
        "categoria em seu UUID antes de registrar uma transação ou orçamento.",
    ),
    _decl(
        "criar_categoria",
        "Cria uma nova categoria de transação.",
        {
            "name": _str("Nome da categoria (ex.: Alimentação)"),
            "description": _str("Descrição opcional da categoria"),
        },
        ["name"],
    ),
    _decl(
        "atualizar_categoria",
        "Atualiza o nome ou a descrição de uma categoria existente.",
        {
            "categoryId": _CATEGORY_ID,
            "name": _str("Novo nome da categoria"),
            "description": _str("Nova descrição (opcional)"),
        },
        ["categoryId", "name"],
    ),
    _decl(
        "excluir_categoria",
        "Exclui uma categoria pelo seu UUID. Operação irreversível.",
        {"categoryId": _CATEGORY_ID},
        ["categoryId"],
    ),
    # Transações
    _decl(
        "criar_transacao",
        "Registra uma nova transação financeira. O usuário DEVE informar se é uma "
        "despesa (EXPENSE) ou receita (INCOME) — se não estiver claro, pergunte. "
        "Resolva nomes de conta e categoria em UUIDs com listar_contas e "
        "listar_categorias antes de chamar. NÃO preencha o campo 'date' a menos "
        "que o usuário mencione explicitamente uma data — quando omitido, o "
        "sistema registra automaticamente com a data de hoje.",
        {
            "amount": _num("Valor da transação (número positivo)"),
            "type": _str(
                "EXPENSE para despesa, INCOME para receita",
                enum=_TRANSACTION_TYPES,
            ),
            "description": _str("Descrição opcional da transação"),
            "date": _str(
                "Data no formato YYYY-MM-DD. Só preencha se o usuário informar "
                "uma data; caso contrário, deixe em branco para usar hoje."
            ),
            "accountId": _ACCOUNT_ID,
            "categoryId": _CATEGORY_ID,
        },
        ["amount", "type", "accountId", "categoryId"],
    ),
    _decl(
        "listar_transacoes",
        "Lista as transações mais recentes, com paginação.",
        {
            "page": _num("Número da página (começa em 0, padrão 0)"),
            "size": _num("Quantidade por página (padrão 20)"),
        },
    ),
    _decl(
        "excluir_transacao",
        "Exclui uma transação pelo seu UUID.",
        {"transactionId": _str("UUID da transação")},
        ["transactionId"],
    ),
    # Orçamentos 
    _decl(
        "listar_orcamentos",
        "Lista os orçamentos, opcionalmente de um mês específico, com o quanto já "
        "foi gasto e o restante de cada categoria.",
        {"month": _str("Mês de referência no formato YYYY-MM (opcional)")},
    ),
    _decl(
        "criar_orcamento",
        "Define um limite de orçamento para uma categoria em um mês de referência.",
        {
            "limitAmount": _num("Valor limite do orçamento (número positivo)"),
            "referenceMonth": _str("Mês de referência no formato YYYY-MM"),
            "categoryId": _CATEGORY_ID,
        },
        ["limitAmount", "referenceMonth", "categoryId"],
    ),
    _decl(
        "atualizar_orcamento",
        "Atualiza o limite de um orçamento existente.",
        {
            "budgetId": _str("UUID do orçamento"),
            "limitAmount": _num("Novo valor limite"),
            "referenceMonth": _str("Mês de referência no formato YYYY-MM"),
            "categoryId": _CATEGORY_ID,
        },
        ["budgetId", "limitAmount", "referenceMonth", "categoryId"],
    ),
    _decl(
        "excluir_orcamento",
        "Remove um orçamento pelo seu UUID.",
        {"budgetId": _str("UUID do orçamento")},
        ["budgetId"],
    ),
]

TOOL_NAMES: frozenset[str] = frozenset(d.name for d in TOOL_DECLARATIONS)

FINANCE_TOOL = types.Tool(function_declarations=TOOL_DECLARATIONS)
