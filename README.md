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
    └── display.py             ← tokens + custo → string colorida
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

### MiniMax quota não aparece (`⏱` ausente)

A barra mostra `⏱ 93% livre (reset 4h42m)` quando o modelo ativo é MiniMax e
a Subscription Key está configurada. Se não aparece:

1. Verifique se `~/.fcc/.env` tem `MINIMAX_API_KEY=...` (a chave do Token Plan,
   não a pay-as-you-go). Veja [MiniMax quota tracking](#minimax-quota-tracking).
2. Rode manualmente pra ver erro:
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '$HOME/Projetos/projetos/claude-code-statusline')
   from lib.minimax_quota import fetch_minimax_quota
   print(fetch_minimax_quota())
   "
   ```
3. Toggle desligado: `statusline.env.json` precisa ter `"show_minimax_quota": true`.

## MiniMax quota tracking

Quando o modelo ativo é da MiniMax (Token Plan), a statusline consulta o
endpoint oficial de quota e mostra o ciclo de 5 horas:

```
[MiniMax-M3·minimax] • ⬆1.2k ⬇350 ↻4.1k • 🇧🇷 R$0.00 • ⏱ 93% livre (reset 4h42m)
```

- **Origem do token:** `MINIMAX_API_KEY` do `~/.fcc/.env` (reutilizado do
  fork `free-claude-code-minimax`). Nenhuma config nova é necessária.
- **Endpoint:** `GET https://www.minimax.io/v1/token_plan/remains` com
  `Authorization: Bearer <Subscription Key>`.
- **Cache:** `~/.cache/claude-code-statusline/minimax-quota.json`, TTL 60s.
- **Cor:** verde < 70% usado, amarelo ≥ 70%, vermelho ≥ 90% (ajustável com
  `quota_warn_pct` / `quota_alert_pct` no `statusline.env.json`).
- **Ciclo semanal:** aparece só quando o upstream reporta `limit > 0`
  (MiniMax Token Plan não tem cap semanal rígido hoje; pode mudar em
  outros providers no futuro).
- **Desativar:** `"show_minimax_quota": false` no `statusline.env.json`.

Para testar manualmente:

```bash
# Com sua Subscription Key (NÃO commitar):
export KEY=$(grep MINIMAX_API_KEY ~/.fcc/.env | cut -d= -f2 | tr -d '"')
/usr/bin/curl -s -X GET https://www.minimax.io/v1/token_plan/remains \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" | python3 -m json.tool
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
   tokens literais. A barra mostra `93% livre` (do `remaining_percent`),
   que é o sinal mais confiável; a contagem exata depende do tier (Plus /
   Max / Ultra) e do tipo de recurso (`general`, `video`, etc.).

## Próximas melhorias (opcional)

- [ ] Tracking per-model em vez de só último modelo
- [ ] Cache write separado de cache read no display
- [ ] Estimativa de "min restantes" baseado no burn rate
- [ ] Hook opcional que dispara alerta se custo > X por hora

## Licença

MIT.
