# BeanBalance Telegram Bot

Assistente financeiro para Telegram que conversa com a stack BeanBalance.
O bot é um **cliente** das APIs existentes (Auth MS + Finance API) — não altera
nenhum código do Spring Boot ou ASP.NET.

> **Status:** Milestone 2 — além do bot em *polling* com allowlist e login,
> existe um cliente tipado para toda a Finance API (contas, categorias,
> transações, orçamentos), com refresh de JWT proativo e reativo (retry em 401).
> O agente Gemini + ferramentas chegam nos próximos milestones.

## Arquitetura

| Módulo | Responsabilidade |
|--------|------------------|
| `bot/config.py` | Carrega e valida variáveis de ambiente em um `BotConfig` tipado |
| `bot/security.py` | `Allowlist` — só IDs de Telegram autorizados interagem |
| `bot/auth_client.py` | Ciclo de vida do JWT: login, cache em memória, refresh e `invalidate()` |
| `bot/models.py` | Modelos tipados (`Account`, `Category`, `Transaction`, `Budget`, `Page`) com dinheiro em `Decimal` |
| `bot/api_client.py` | `BeanBalanceApiClient` — 17 endpoints REST, header de auth, retry em 401 |
| `bot/main.py` | App `python-telegram-bot` (polling): handlers, guarda de allowlist, login no startup |

O `AuthClient` separa a **política** (quando renovar/relogar) da **I/O** HTTP
(`HttpTokenProvider`), que envolve `httpx`. Isso mantém a política testável sem
rede. O `BeanBalanceApiClient` depende apenas do protocolo `Authorizer`
(implementado pelo `AuthClient`), então também é testável com transportes
`httpx.MockTransport`.

### Refresh de JWT (duas camadas)

1. **Proativo:** o `AuthClient` renova o token quando faltam ≤ 5 min para expirar.
2. **Reativo:** se a API responde `401` (token revogado antes de expirar), o
   `api_client` chama `authorizer.invalidate()` e refaz a requisição uma vez.

## Configuração

```bash
cp .env.example .env
# preencha TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, BEANBALANCE_*, ALLOWED_TELEGRAM_IDS
```

| Variável | Descrição |
|----------|-----------|
| `TELEGRAM_BOT_TOKEN` | Token do @BotFather |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Credenciais do Gemini (usadas a partir do Milestone 3) |
| `BEANBALANCE_API_URL` | URL base (sem barra final); o bot anexa `/api/auth/...` e `/api/...` |
| `BEANBALANCE_EMAIL` / `BEANBALANCE_PASSWORD` | Credenciais da sua conta BeanBalance |
| `ALLOWED_TELEGRAM_IDS` | IDs do Telegram autorizados, separados por vírgula |
| `CONVERSATION_MEMORY_SIZE` | Tamanho do histórico de conversa (default 10) |

Para criar o bot e descobrir seu Telegram ID, veja a seção
"Como Criar o Bot no Telegram" no `implementation_plan.md` da raiz.

## Desenvolvimento local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# Rodar os testes
.venv/bin/python -m pytest

# Rodar o bot (lê .env automaticamente)
.venv/bin/python -m bot.main
```

## Docker

```bash
docker compose up -d --build
```

Em modo polling o bot só faz conexões de saída — não precisa de domínio, porta
aberta ou certificado SSL.
