# claude-code-statusline

Statusline custom para Claude Code que mostra **tokens e custo estimado em
tempo real**, mesmo se você trocar de provider no meio da sessão.

Funciona com o Claude Code puro, `fcc-claude` (free-claude-code), ou qualquer
wrapper que use o formato de log JSONL padrão do Claude Code.

## O que mostra

Formato compacto (default):

```
[MiniMax-M3·minimax] • ⬆12.3k ⬇3.4k ↻13.2k • 🇧🇷 R$0.42 🇺🇸 $0.08 • 18m • 65t/m
```

| Campo | Significado |
|---|---|
| `[MiniMax-M3·minimax]` | modelo + provider ativo |
| `⬆12.3k` | tokens de input somados na sessão |
| `⬇3.4k` | tokens de output |
| `↻13.2k` | cache_read + cache_creation (leitura de cache) |
| `🇧🇷 R$0.42` | custo estimado em BRL (cotação do dia) |
| `🇺🇸 $0.08` | mesmo custo em USD |
| `18m` | duração da sessão |
| `65t/m` | burn rate (input+output por minuto) |

Cores (ANSI, desativáveis via `STATUSLINE_COLOR=never`):

- **Verde**: custo < R$ 0.50, burn rate < 1500 t/m
- **Amarelo**: R$ 0.50–2.50, 1500–5000 t/m
- **Vermelho**: ≥ R$ 2.50, ≥ 5000 t/m
- **Cinza**: free tier ou Token Plan (sem custo monetário)
- **Ciano** no `[modelo·provider]`: destaca o provider atual

## Como funciona

1. Claude Code loga cada mensagem do assistant em JSONL
   (`~/.claude/projects/<hash>/<session-id>.jsonl`)
2. Claude Code executa a `statusLine.command` periodicamente
   (configurável em `refreshInterval`)
3. Script Python:
   - lê o JSONL da sessão atual (via `$CLAUDE_SESSION_ID`)
   - soma `input_tokens`, `output_tokens`, `cache_creation`, `cache_read`
   - identifica o último modelo (pode ter trocado no meio)
   - calcula custo via `pricing.json`
   - formata string colorida e printa em stdout

**Latência:** ~50ms por execução (cold start do Python). O Claude Code
normalmente cacheia o processo, então na prática fica < 20ms.

## Instalação

```bash
# 1. Clonar/copiar o projeto para ~/Projetos/projetos/claude-code-statusline
#    (já está feito se você usou o setup da central)

# 2. Criar symlink (já feito pelo setup, mas caso precise refazer):
rm -rf ~/.claude/statusline
ln -s ~/Projetos/projetos/claude-code-statusline ~/.claude/statusline

# 3. Adicionar em ~/.claude/settings.json:
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline/session_tokens.py",
    "refreshInterval": 5000
  }
}

# 4. Reiniciar Claude Code (se estiver aberto)
```

## Configuração de display (opcional)

Crie `~/.claude/statusline/statusline.env.json` para customizar o que
aparece e os thresholds de alerta:

```json
{
  "show_provider": true,
  "show_model": true,
  "show_tokens": true,
  "show_cost": true,
  "show_duration": true,
  "show_burn_rate": true,
  "show_cache_pct": true,
  "show_flags": true,
  "show_both_currencies": true,
  "verbose": false,
  "color": "auto",
  "cost_warn_brl": 0.50,
  "cost_alert_brl": 2.50,
  "burn_warn_per_min": 1500,
  "burn_alert_per_min": 5000,
  "fx_cache_ttl_seconds": 3600
}
```

| Opção | Default | Significado |
|---|---|---|
| `show_flags` | `true` | Mostra bandeirinhas 🇧🇷 🇺🇸 |
| `show_both_currencies` | `true` | Mostra BRL e USD juntos |
| `verbose` | `false` | Se `true`, mostra USD também (se `show_both_currencies=false`) |
| `color` | `"auto"` | `"always"`, `"auto"` ou `"never"` |
| `cost_warn_brl` | 0.50 | Cor amarela a partir desse valor |
| `cost_alert_brl` | 2.50 | Cor vermelha a partir desse valor |
| `burn_warn_per_min` | 1500 | Burn rate amarelo (tokens/min) |
| `burn_alert_per_min` | 5000 | Burn rate vermelho (com prefixo `⚠`) |
| `fx_cache_ttl_seconds` | 3600 | TTL do cache de cotação (1h) |

## Câmbio de moeda (USD ↔ BRL)

A statusline busca a cotação do dólar em tempo real via **AwesomeAPI**
(`https://economia.awesomeapi.com.br/last/USD-BRL`), gratuita e sem auth.

- **Primeira execução:** busca na API, salva em `~/.cache/claude-code-statusline/fx.json`
- **Execuções seguintes (até 1h):** lê do cache (não chama rede)
- **API fora do ar:** fallback para `fx_to_brl` definido em `pricing.json`
- **Statusline mostra `(fx=fallback)` ou `(fx=2.3h)` no fim** se a cotação estiver velha ou vier de fallback

A cotação exibida é o **`bid`** (preço de compra) — convenção do mercado
câmbio brasileiro. Se preferir usar **mid** (média entre bid e ask),
edite `lib/fx.py`.

## Customizando preços (pricing.json)

Edite `pricing.json` para adicionar novos modelos ou atualizar preços.

```json
{
  "currency": "USD",
  "fx_to_brl": 5.20,
  "models": {
    "minimax/MiniMax-M3": {
      "provider": "minimax",
      "display": "MiniMax-M3",
      "input": 0.21,
      "output": 0.84,
      "cache_read": 0.02,
      "cache_write": 0.21,
      "unit": "per_million_tokens",
      "billing_mode": "pay_as_you_go"
    }
  },
  "fallback": {
    "provider": "unknown",
    "display": "???",
    "input": 0.0, "output": 0.0,
    "cache_read": 0.0, "cache_write": 0.0,
    "billing_mode": "unknown"
  }
}
```

`billing_mode` controla como o custo aparece:

- `"pay_as_you_go"` (default) — calcula USD × FX, mostra em BRL colorido
- `"free_tier"` — mostra `R$ 0.00 (free)` em cinza
- `"token_plan"` — mostra `R$ 0.00 (quota)` em amarelo dim (consome quota do plano)

Para MiniMax Token Plan, mude o `billing_mode` do `MiniMax-M3` para
`"token_plan"` se quiser refletir que a Subscription Key usa quota.

## Estrutura do projeto

```
~/Projetos/projetos/claude-code-statusline/
├── README.md                  ← você está aqui
├── pricing.json               ← tabela de preços
├── statusline.env.json        ← (opcional) toggles de display
├── session_tokens.py          ← entry point
└── lib/
    ├── __init__.py
    ├── parser.py              ← JSONL → TokenTotals
    ├── pricing.py             ← modelo → CostBreakdown
    ├── provider_quota.py      ← adapters de quota (MiniMax, OpenRouter, ...)
    └── display.py             ← tokens + custo → string colorida
```

## Providers suportados e quota adapters

O statusline mostra tokens, custo, cache R/W e burn rate para **todos os 18
providers** do fcc-claude. O segmento `⏱` de quota aparece **apenas** quando o
provider ativo tem um adapter vivo registrado.

| Provider | Custo | Tokens | Cache R/W | Quota (`⏱`) |
|---|---|---|---|---|
| `nvidia_nim` | sim | sim | sim | — sem API pública |
| `open_router` | sim | sim | sim | **sim** (credits API) |
| `gemini` | sim | sim | sim | — sem API pública |
| `deepseek` | sim | sim | sim | **sim** (`/user/balance`) |
| `mistral` | sim | sim | sim | **sim** (`/v1/usage`) |
| `mistral_codestral` | sim | sim | sim | **sim** (via alias → `mistral`) |
| `opencode` | sim | sim | sim | — |
| `opencode_go` | sim | sim | sim | — |
| `wafer` | sim | sim | sim | — |
| `kimi` | sim | sim | sim | — |
| `cerebras` | sim | sim | sim | — |
| `groq` | sim | sim | sim | — |
| `fireworks` | sim | sim | sim | — |
| `zai` | sim | sim | sim | — |
| `lmstudio` | sim | sim | sim | — |
| `llamacpp` | sim | sim | sim | — |
| `ollama` | sim | sim | sim | — |
| `minimax` | sim | sim | sim | **sim** (Token Plan 5h+week) |
| OpenAI (admin) | sim | sim | sim | **sim** (`/v1/dashboard/billing/credit_grants`) |

> **Codex / ChatGPT Plus-Pro-Business-Edu-Enterprise:** detecta automaticamente
> quando o model ativo começa com `gpt-` ou `o1`-`o5` E existe `~/.codex/auth.json`
> (do `codex login`) com JWT válido. Mostra o plano + limite conhecido, sem
> usage real (OpenAI não expõe subscription quota via API pública).
> 
> **OpenAI admin dashboard (gpt-/o1-/o3-/etc sem codex):** ativa quando o
> model tem shape Codex mas o Codex auth NÃO está presente E `OPENAI_API_KEY`
> está set. Requer **admin key** (sk- regular retorna 403; o adapter omite o
> segmento nesse caso).

### Quota adapters ativos

| Provider | Endpoint | Auth | Formato exibido |
|---|---|---|---|
| `minimax` | `GET https://www.minimax.io/v1/token_plan/remains` | `MINIMAX_API_KEY` (env ou `~/.fcc/.env`) | `⏱ 60% usado (40% livre) (reset 2h48m)` |
| `open_router` | `GET https://openrouter.ai/api/v1/credits` | `OPENROUTER_API_KEY` (env ou `~/.fcc/.env`) | `⏱ 25% usado (75% livre) ($2.50 used of $10.00)` |
| `deepseek` | `GET https://api.deepseek.com/user/balance` | `DEEPSEEK_API_KEY` (env ou `~/.fcc/.env`) | `⏱ $4.50 USD (usou $0.50 de $5.00 free)` |
| `mistral` | `GET https://api.mistral.ai/v1/usage` | `MISTRAL_API_KEY` (env ou `~/.fcc/.env`) | `⏱ 1.7M tokens (modelos: mistral-large-latest, mistral-small-latest)` |
| `openai_dashboard` | `GET https://api.openai.com/v1/dashboard/billing/credit_grants` | `OPENAI_API_KEY` (admin only) | `⏱ 12% usado (88% livre) ($12.00 used of $100.00)` |
| `codex_chatgpt` | Lê `~/.codex/auth.json` e decodifica JWT (sem rede) | `~/.codex/auth.json` ou `$CODEX_ACCESS_TOKEN` | `⏱ Plus (80 msgs / 3h) (limite OpenAI pode mudar)` |

Aliases:
* `codestral` → `mistral` (o gateway `codestral` do fcc-claude atinge o
  mesmo backend Mistral, então o uso aparece no `/v1/usage` da Mistral).

Adicionar novo adapter: implementar `QuotaProvider` em `lib/provider_quota.py` e
registrar em `QUOTA_PROVIDERS`.

## Cores do quota segment (`⏱`)

Os adapters que expõem `used_pct` (MiniMax, OpenRouter, OpenAI dashboard)
renderizam o label no formato **`X% usado (Y% livre)`** (espelhando o
segmento `🧠` de contexto) com cor que escala intuitivamente: quanto
maior o número, mais perto do limite, mais quente a cor.

| Cor | Condição | Significado |
|---|---|---|
| 🟢 verde | `used_pct < 60%` | Saudável |
| 🟡 amarelo | `60% ≤ used_pct < 85%` | Warning — começa a apertar |
| 🔴 vermelho | `used_pct ≥ 85%` | Alerta — perto do limite |

Exemplos de output:

```
# 30% usado (verde)
⏱ 30% usado (70% livre) (reset 2h48m)

# 60% usado (amarelo)
⏱ 60% usado (40% livre) (reset 45m)

# 85% usado (vermelho)
⏱ 85% usado (15% livre) (reset 5m)
```

Para customizar os thresholds, edite `statusline.env.json`:

```json
{
  "quota_warn_pct": 60,    // amarelo começa aqui (default)
  "quota_alert_pct": 85    // vermelho começa aqui (default)
}
```

Para desativar as cores: `"color": "never"` no `statusline.env.json`
(também remove as cores do restante da statusline).

Provedores sem `used_pct` (DeepSeek balance absoluto, Mistral sem hard
limit, Codex ChatGPT estático) continuam com a cor cinza neutra.

## OpenAI / Codex ChatGPT plan tracking

Quando o model ativo é da família OpenAI GPT/o-series (`gpt-5`, `gpt-4o`,
`gpt-5-codex`, `o3`, etc.) E o usuário está logado no Codex CLI
(`codex login` com ChatGPT Plus/Pro/Business/Edu/Enterprise), a statusline
mostra o plano detectado:

```
[gpt-5-codex] • ⬆4.5k ⬇1.2k ↻R12k • ⏱ Plus (80 msgs / 3h) (limite OpenAI pode mudar)
```

- **Origem do token:** lê `~/.codex/auth.json` (escrito pelo `codex login`).
  Também aceita `$CODEX_ACCESS_TOKEN` env var.
- **Endpoint:** nenhum — o statusline decodifica o JWT salvo localmente
  (sem chamada de rede). O Codex já gravou o token após OAuth.
- **Claim usada:** `https://api.openai.com/auth.chatgpt_plan_type` no payload
  do JWT, parseada conforme `codex-rs/login/src/token_data.rs`.
- **Limites conhecidos** (tabela hardcoded — OpenAI pode mudar):

  | Plano | Limite exibido |
  |---|---|
  | `free` | `3 msgs / 40h` |
  | `plus` | `80 msgs / 3h` |
  | `pro` | `500 msgs / 3h` |
  | `business` | `100 msgs / 3h` |
  | `enterprise` | `1000 msgs / 3h` |
  | `edu` | `50 msgs / 3h` |
  | `team` | `100 msgs / 3h` |
  | _outros_ | `limite desconhecido` |

- **Sem usage real:** OpenAI **não expõe** quota restante de subscription
  via API pública. Os headers `x-ratelimit-*` em responses são de tier de
  API key, não de subscription. Por isso o adapter mostra só o **limite
  estático** do plano + nota `limite OpenAI pode mudar`.
- **Sem countdown:** reset windows da subscription não são documentados.
- **Segurança:** decodificamos o JWT **sem verificar assinatura**. Usamos só
  pra extrair claim informativa (chatgpt_plan_type) — jamais pra autorização.
  É o mesmo padrão que o `codex login status` faz internamente.
- **Cache:** `~/.cache/claude-code-statusline/provider-quota.json`, TTL 60s.

Para testar manualmente:

```bash
# 1. Login no Codex CLI
codex login   # segue fluxo OAuth

# 2. Rode o script diretamente
python3 ~/.claude/statusline/session_tokens.py
# Vai detectar ~/.codex/auth.json e mostrar o plano
```

## Troubleshooting

### Statusline não aparece no TUI

1. Verifique se `~/.claude/settings.json` tem o campo `statusLine`.
2. Rode manualmente: `python3 ~/.claude/statusline/session_tokens.py` — deve
   retornar uma string em < 100ms.
3. Reinicie o Claude Code (`Ctrl+D`, depois `fcc-claude`).

### Custo sempre `R$ 0.00`

- Modelo não está na `pricing.json` — adicione a entrada.
- `billing_mode` está como `"free_tier"` ou `"token_plan"`.

### Modelo aparece como `[???]`

- A sessão ainda não tem nenhum request do assistant (só user/system).
- `$CLAUDE_SESSION_ID` não está chegando ao script. Verifique se está
  usando uma versão do Claude Code ≥ 2.1.

### Burn rate inflado

- O burn rate usa só `input_tokens + output_tokens` (não cache).
- Se ainda parecer alto, a sessão é realmente muito ativa — normal em
  tarefas de refactor grande com `MiniMax-M3`.

### Quota adapter ausente (`⏱` não aparece)

A linha `⏱` só renderiza quando o provider ativo tem um adapter vivo em
`lib/provider_quota.py::QUOTA_PROVIDERS`. Hoje: **MiniMax + OpenRouter**.
Para os 16 providers sem adapter público (gemini, kimi, ollama, etc.), a
linha **simplesmente some** — é o comportamento correto, não um bug.

### MiniMax quota não aparece mesmo com `MODEL=minimax/MiniMax-M3`

1. Verifique se `~/.fcc/.env` tem `MINIMAX_API_KEY=...` (Subscription Key
   do Token Plan, não pay-as-you-go).
2. Rode manualmente pra ver erro:
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '$HOME/Projetos/projetos/claude-code-statusline')
   from lib.provider_quota import fetch_quota
   print(fetch_quota('minimax'))
   "
   ```
3. Toggle desligado: `statusline.env.json` precisa ter `"show_provider_quota": true`.

## MiniMax quota tracking

Quando o modelo ativo é `minimax/*`, a statusline consulta o endpoint
oficial do Token Plan e mostra o ciclo de 5 horas:

```
[MiniMax-M3·minimax] • ⬆1.2k ⬇350 ↻R4.1k • ⏱ 93% usado (7% livre) (reset 4h42m)
```

- **Origem do token:** `MINIMAX_API_KEY` do `~/.fcc/.env` (reutilizado do
  fork `free-claude-code-minimax`).
- **Endpoint:** `GET https://www.minimax.io/v1/token_plan/remains` com
  `Authorization: Bearer <Subscription Key>`.
- **Cache:** `~/.cache/claude-code-statusline/provider-quota.json`, TTL 60s.
- **Cor:** verde < 60% usado, amarelo ≥ 60%, vermelho ≥ 85% (ajustável via
  `quota_warn_pct` / `quota_alert_pct` em `statusline.env.json`).
- **Desativar:** `"show_provider_quota": false` no `statusline.env.json`.

Para testar manualmente:

```bash
# Com sua Subscription Key (NÃO commitar):
export KEY=$(grep MINIMAX_API_KEY ~/.fcc/.env | cut -d= -f2 | tr -d '"')
/usr/bin/curl -s -X GET https://www.minimax.io/v1/token_plan/remains \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" | python3 -m json.tool
```

## OpenRouter credits tracking

Quando o modelo ativo é `open_router/*`, a statusline consulta o endpoint
de credits do OpenRouter e mostra o percentual usado:

```
[anthropic/claude-sonnet-4·open_router] • ⬆12k ⬇1k ↻0 • ⏱ 25% usado ($2.50 used of $10.00)
```

- **Origem do token:** `OPENROUTER_API_KEY` do `~/.fcc/.env` ou env var.
- **Endpoint:** `GET https://openrouter.ai/api/v1/credits` com
  `Authorization: Bearer <Key>`.
- **Cache:** mesmo arquivo do MiniMax (`provider-quota.json`).

Para testar manualmente:

```bash
/usr/bin/curl -s -X GET https://openrouter.ai/api/v1/credits \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" | python3 -m json.tool
```

## Limitações conhecidas

1. **Não detecta Token Plan ativo** — você precisa setar `billing_mode` manualmente.
2. **Custo agregado por último modelo** — se você alternou entre providers
   na mesma sessão, o custo total reflete o preço do último modelo (não
   faz rateio por modelo individual).
3. **Cache não-rateado por provider** — `cache_read` é tratado com o preço
   do último modelo (pode ser impreciso se você trocou).
4. **Não considera tiered pricing** — se um modelo cobra mais caro acima de
   200k tokens, isso não é detectado.
5. **RefreshInterval mínimo** — Claude Code tem mínimo de 1s; valores
   menores são ignorados.
6. **Quota MiniMax é quota units, não tokens** — o endpoint
   `/v1/token_plan/remains` retorna `current_interval_total_count` /
   `current_interval_usage_count` em unidades de quota do plano, não em
   tokens literais. A barra mostra `93% usado (7% livre)` (calculado a
   partir de `remaining_percent`), que é o sinal mais confiável; a
   contagem exata depende do tier (Plus / Max / Ultra) e do tipo de
   recurso (`general`, `video`, etc.).

## Inspiração: cc-statusline upstream

A inspiração visual original veio do projeto community `Miluer-tcq/cc-statusline`.
Este projeto é **independente** (reescrito em Python + pricing dinâmico + quota
MiniMax + cache R/W + burn rate 🧊⚡🔥) e **não é um fork**.

Para não perder novidades do upstream, `.github/workflows/watch-cc-statusline-upstream.yml`
roda toda segunda 9h BRT e abre uma issue listando os commits novos do upstream.
**Nenhum merge é feito automaticamente** — a issue serve como lista de leitura
pra você escolher manualmente o que portar.

Workflow:
1. Lê `.github/upstream-sha` (SHA conhecido) e busca HEAD do upstream via `git ls-remote`.
2. Se mudou: chama GitHub compare API pra listar commits novos.
3. Abre/atualiza issue com label `upstream-watch`.
4. Bumpa o SHA conhecido (commit automático via `github-actions[bot]`).

## Próximas melhorias (opcional)

- [ ] Tracking per-model em vez de só último modelo
- [ ] Cache write separado de cache read no display
- [ ] Estimativa de "min restantes" baseado no burn rate
- [ ] Hook opcional que dispara alerta se custo > X por hora

## Licença

MIT.
