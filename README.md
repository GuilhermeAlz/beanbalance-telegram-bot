# BeanBalance Telegram Bot

Assistente financeiro para Telegram que conversa com a stack BeanBalance.
O bot é um **cliente** das APIs existentes (Auth MS + Finance API) — não altera
nenhum código do Spring Boot ou ASP.NET.

> **Status:** Milestone 3 — o bot agora conversa em linguagem natural. As
> mensagens de texto passam pelo agente Gemini, que decide quais ferramentas
> chamar (16 ferramentas sobre toda a Finance API) e responde em pt-BR. Sobre as
> bases dos milestones anteriores: *polling* com allowlist, login e refresh de
> JWT (proativo + reativo), e cliente tipado da Finance API.

## Arquitetura

| Módulo | Responsabilidade |
|--------|------------------|
| `bot/config.py` | Carrega e valida variáveis de ambiente em um `BotConfig` tipado |
| `bot/security.py` | `Allowlist` — só IDs de Telegram autorizados interagem |
| `bot/auth_client.py` | Ciclo de vida do JWT: login, cache em memória, refresh e `invalidate()` |
| `bot/models.py` | Modelos tipados (`Account`, `Category`, `Transaction`, `Budget`, `Page`) com dinheiro em `Decimal` |
| `bot/api_client.py` | `BeanBalanceApiClient` — 17 endpoints REST, header de auth, retry em 401 |
| `bot/tools.py` | 16 declarações de ferramentas (`FunctionDeclaration`) do Gemini, em pt-BR |
| `bot/tool_executor.py` | `ToolExecutor` — despacha tool calls para o `api_client`; erros viram resultado amigável |
| `bot/agent.py` | Loop agêntico Gemini (`Agent` + `GeminiClient`): tool calls + memória de conversa |
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

### Agente (Gemini + ferramentas)

Cada mensagem de texto vira uma chamada a `Agent.handle(chat_id, mensagem)`:

1. Monta `contents` = histórico da conversa + a nova mensagem.
2. Pergunta ao Gemini. Se ele pedir *tool calls*, o `ToolExecutor` executa cada
   uma contra a Finance API e devolve o resultado como `function_response`.
3. Repete até o modelo responder em texto — no máximo **5 iterações** de
   ferramentas por mensagem (evita loops).

A memória é uma janela rolante por chat (`CONVERSATION_MEMORY_SIZE` mensagens);
`/reset` a limpa. O loop depende apenas do protocolo `LlmClient`, então é testado
sem rede — `GeminiClient` é o adaptador fino sobre o SDK `google-genai` (async).

**Comandos:** `/start`, `/help`, `/reset`. Qualquer outro texto passa pelo agente.

## Configuração

```bash
cp .env.example .env
# preencha TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, BEANBALANCE_*, ALLOWED_TELEGRAM_IDS
```

| Variável | Descrição |
|----------|-----------|
| `TELEGRAM_BOT_TOKEN` | Token do @BotFather |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Chave e modelo do Gemini que alimentam o agente |
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
