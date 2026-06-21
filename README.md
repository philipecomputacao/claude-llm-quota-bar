# claude-llm-quota-bar

> **A multi-provider statusline script for [Claude Code][claude-code].**
> Live token + cost + burn-rate + **provider quota** bar with colour-coded alerts.

[claude-code]: https://docs.claude.com/en/docs/claude-code

[![license](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![CI](https://github.com/philipecomputacao/claude-llm-quota-bar/actions/workflows/ci.yml/badge.svg)](https://github.com/philipecomputacao/claude-llm-quota-bar/actions/workflows/ci.yml)
![status](https://img.shields.io/badge/status-stable-brightgreen.svg)
![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![providers](https://img.shields.io/badge/providers-18%2B-orange.svg)
![claude--code](https://img.shields.io/badge/Claude%20Code-statusline-purple.svg)
![models](https://img.shields.io/badge/models-402-yellow.svg)
[![@lpdigital.me](https://img.shields.io/badge/maintained%20by-%40lpdigital.me-E4405F.svg)](https://www.instagram.com/lpdigital.me/)

---

## Highlights

- 🧠 **Built for Claude Code, first** — tracks native Claude sessions out of
  the box: per-message tokens, cache reads/writes, context window %, and
  burn rate (`🧊` / `⚡` / `🔥`) in colour-coded lines.
- 📊 **Live quota when you route elsewhere** — extend the bar with the
  `⏱` segment for [MiniMax Token Plan](https://platform.minimax.io),
  OpenRouter credits, DeepSeek balance, Mistral usage, OpenAI credit
  grants, and Codex ChatGPT plan. Falls back gracefully when no key is set.
- 💰 **Cost in BRL + USD** with a cached FX rate (refreshes hourly).
- 🔖 **Session resume bookmark** — copy `claude --resume <id>` straight
  from the statusline. Auto-detects the launcher (`fcc-claude` vs `claude`).
  Colour signals whether the id is the active window's session or was inferred
  from the most-recent JSONL.
- 🔀 **Git-aware** — the 5th line shows the current branch and the last
  commit. The branch colour reflects working-tree dirtyness vs HEAD: cyan
  when clean, yellow at 50+ lines pending, red at 300+.
- 🌐 **Router-aware** — the 🌐 segment on the cost line shows whether the
  active session is going through `fcc-claude`'s local proxy and whether
  the proxy is actually responding. Soft green when alive, red when the
  proxy crashed, grey `router desativado` for vanilla Claude Code. Probes
  every 45s (configurable) so the verdict stays fresh without hammering
  the proxy.
- 🛡️ **Resilient by default** — every render is wrapped in a try/except so
  a stray crash never blanks the statusline. The bar shows
  `[sem sessão] (erro: <Type>)` instead. Git subprocesses run under a 3.5s
  cumulative budget so a slow repo can't blow past the 5s refresh tick.
- 🔌 **402 models** with auto-pricing from upstream `pricing.json`
  (Anthropic, OpenAI, Google, Mistral, DeepSeek + 18+ gateway pass-throughs).
- 🪟 **Drop-in statusline script**: invoked by Claude Code as a Python
  subprocess on every refresh tick — zero daemons, no background
  service to install.
- 🔒 **Zero secrets in repo** — keys live in your shell env or `~/.fcc/.env`
  and are referenced by name only. See [SECURITY.md](SECURITY.md).

---

## What you get

Native Claude Code session (no API key needed for the quota segment):

```
📁 ~/src/my-project
[claude-sonnet-4-5] • 📟 v2.1.170 • 🔖 claude --resume f47ac10b-...-4aae
⬆1.0M ⬇48k ↻R2.8M • 🧠 12% usado (88% livre)
🇧🇷 R$1.61 🇺🇸 $0.312 • ⌛ 25m • ⚡ 42951t/m • 🌐 http://localhost:8082
🔀 main • 1a2b3c4 • fix: correct off-by-one in user count
```

Routed through a third-party provider with a quota adapter enabled
(`MINIMAX_API_KEY` set in this example):

```
📁 ~/src/my-project
[MiniMax-M3·minimax] • 📟 v2.1.170 • 🔖 claude --resume f47ac10b-...-4aae
⬆1.0M ⬇48k ↻R2.8M • ⏱ 40% usado (60% livre) (reset 2h48m) • 🧠 12% usado (88% livre)
🇧🇷 R$1.61 🇺🇸 $0.312 • ⌛ 25m • ⚡ 42951t/m • 🌐 http://localhost:8082
🔀 feature/quota • 9c8b7a6 • feat(quota): add OpenAI credit grants adapter • +153/-22
```

| Field | What it tells you |
|---|---|
| `[model·provider]` | Active model and upstream provider (gateway suffixes stripped — ``minimax`` stays, ``opencode_go`` doesn't) |
| `📁 cwd` | Full working directory on its own line — never truncated |
| `📟 vX.Y.Z` | Claude Code version (hidden for unrecognised build strings) |
| `🔖 launcher --resume <id>` | Copy-pasteable bookmark to reopen this session in another window. <br>Colour: `CYAN` = this window's exact session, `DIM` = inferred from most-recent JSONL (sibling window). <br>Auto-detects `claude` vs `fcc-claude` so the command works without editing. |
| `⬆ input  ⬇ output  ↻R cache-read` | Token usage breakdown, with cache reads shown separately (green) |
| `⏱ X% usado (Y% livre) (reset 2h)` | Live quota from the **provider's own API** — colour-coded by usage |
| `🧠 X% usado (Y% livre)` | Context window usage, same colour rule |
| `🇧🇷 R$ X  🇺🇸 $ Y` | Cost in both currencies (FX rate cached) |
| `⌛ 25m` | Wall-clock session duration |
| `⚡ 42951t/m` | Burn rate with 🧊 / ⚡ / 🔥 emoji by tier |
| `🔀 branch • hash • title • +N/-M` | Git metadata for the project cwd. <br>Branch colour reflects **working-tree dirtyness** vs HEAD: <br>🟢 cyan (0 lines) · 🟡 yellow (50+ lines) · 🔴 red (300+ lines). <br>`+N/-M` suffix only appears when dirty. <br>Greyed-out `🔀 [sem git]` when not a repo — keeps vertical rhythm stable. |
| `🌐 <url>` (router alive) | Local proxy in use — `ANTHROPIC_BASE_URL` points at a local host **and** the proxy answered the last health probe. Soft green (`DIM + GREEN`). |
| `🌐 <url>` (router down)  | Same URL but the health probe reported `"down"` (TCP refused / timeout). Red — restart `fcc-server`. |
| `🌐 router desativado`    | Native Claude Code or third-party API — no local proxy configured. Grey. |

All segments are independently toggleable. All thresholds are configurable.

---

## Why this exists

Claude Code's built-in statusline is a one-liner with the model name. If you:

- use **native Claude Code** and want a glanceable summary of tokens,
  context window %, cost, and burn rate that the built-in statusline
  doesn't show
- route Claude Code through **18+ LLM providers** (Claude, MiniMax,
  OpenRouter, OpenAI, Codex, DeepSeek, Mistral, Groq, Cerebras, Fireworks,
  ZAI, Kimi, NVIDIA NIM, Ollama, LlamaCPP, LMStudio, Wafer, …) and want
  to track **per-provider quota** in real time
- burn through **MiniMax Token Plan** windows and need to know exactly when
  the 5h counter resets
- run on **OpenRouter credits** and need a glance-able `$2.50 used of $10.00`
- use **ChatGPT Plus/Pro via Codex CLI** and want your plan badge in the bar
- are cost-conscious and need **BRL ↔ USD** with a cached FX rate

…this script is for you. It started as a fork of
[Miluer-tcq/cc-statusline](https://github.com/Miluer-tcq/cc-statusline) but
the upstream has since been rewritten in bash; this repo stays on **Python 3**
with first-class multi-provider quota tracking. See
[Upstream history](#upstream-history) for the full story.

---

## Table of contents

- [Quick start](#quick-start)
  - [0. Install with an AI assistant](#0-install-with-an-ai-assistant-recommended-if-youre-not-technical)
- [Providers supported](#providers-supported)
- [Quota adapters](#quota-adapters)
- [Colour rules](#colour-rules)
- [Router segment (🌐)](#router-segment-)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Adding a new provider](#adding-a-new-provider)
- [Adding a new quota adapter](#adding-a-new-quota-adapter)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Related projects](#related-projects)
- [Upstream history](#upstream-history)
- [License](#license)
- [Security](#security)

---

## Quick start

### 0. Install with an AI assistant (recommended if you're not technical)

Copy the prompt below and paste it into any AI chat (ChatGPT, Claude,
Gemini, etc.). The assistant will install the bar end-to-end on your
machine — no programming knowledge required on your side.

<details>
<summary><strong>Click to reveal the install prompt — copy everything inside the box</strong></summary>

```plaintext
You are helping me install "claude-llm-quota-bar", a small Python 3
statusline script for Claude Code (the Anthropic CLI for AI-assisted
coding). It renders a colour-coded bar in the Claude Code TUI showing
the active model, token usage, cost, burn rate, and (optionally) live
quota for the routed provider.

Your job: install it on my machine end-to-end and verify it works.
Do not ask me coding questions — make sensible decisions and tell me
what you did. If you hit a step that needs my input (e.g. choosing
between macOS Terminal and iTerm), ask exactly one focused question
and continue.

=========================================================
STEP 1 — Detect my environment
=========================================================
Run these commands and remember the output:

  uname -a                          # OS family (Darwin / Linux / Windows-bash)
  python3 --version                 # need 3.10+
  git --version                     # need any modern git
  command -v claude                 # is Claude Code already installed?
  command -v fcc-claude             # is the free-claude-code wrapper installed?
  echo "BASE_URL=${ANTHROPIC_BASE_URL:-<unset>}"   # is a local proxy already configured?

If python3 is missing, tell me to install it from https://python.org
(macOS / Windows) or `sudo apt install python3` (Debian/Ubuntu) and
stop. If git is missing, tell me to install it and stop.

=========================================================
STEP 2 — Install the script
=========================================================
Run ONE of these (pick the first one that matches my environment):

  # macOS / Linux (most common — uses git clone)
  git clone https://github.com/philipecomputacao/claude-llm-quota-bar.git \
      ~/src/claude-llm-quota-bar
  mkdir -p ~/.claude/statusline
  ln -sf ~/src/claude-llm-quota-bar/session_tokens.py \
         ~/.claude/statusline/session_tokens.py

  # Windows (Git Bash / WSL — same commands, but use $HOME instead of ~)
  git clone https://github.com/philipecomputacao/claude-llm-quota-bar.git \
      "$HOME/src/claude-llm-quota-bar"
  mkdir -p "$HOME/.claude/statusline"
  ln -sf "$HOME/src/claude-llm-quota-bar/session_tokens.py" \
         "$HOME/.claude/statusline/session_tokens.py"

  # If git clone fails (no git, no internet, corporate firewall), fall
  # back to direct download — single file, no git history:
  curl -fsSL https://raw.githubusercontent.com/philipecomputacao/claude-llm-quota-bar/main/session_tokens.py \
      -o ~/.claude/statusline/session_tokens.py
  chmod +x ~/.claude/statusline/session_tokens.py

After install, run this and verify it exits 0 with empty stdout:

  python3 ~/.claude/statusline/session_tokens.py < /dev/null

If it errors with "No module named 'X'", that's impossible — the
script uses Python stdlib only. If it errors with "Permission denied",
re-run with `chmod +x` and try again. Otherwise paste me the error.

=========================================================
STEP 3 — Wire it into Claude Code
=========================================================
Open the file ~/.claude/settings.json (create it if it doesn't exist)
and add (or merge into the existing JSON):

  {
    "statusLine": {
      "type": "command",
      "command": "python3 ~/.claude/statusline/session_tokens.py",
      "refreshInterval": 10000
    }
  }

If settings.json already has a `statusLine` key, REPLACE it (don't
duplicate). If the file has other settings (mcpServers, permissions,
etc.), preserve them — only touch the statusLine block.

If the path to python3 is `~/.local/share/uv/tools/.../bin/python3`
(use `which python3` to check), use that exact path instead of the
bare `python3` — some Claude Code installs don't put python on PATH.

=========================================================
STEP 4 — Verify it works
=========================================================
Restart Claude Code (close and reopen the TUI). Type any short
prompt. The statusline at the bottom of the TUI should now show
multiple lines including the model name, token counts, and a cost
in R$ and $.

If the statusline is empty or still shows Claude Code's built-in
one-liner, the most common cause is that settings.json has bad
JSON. Run `python3 -m json.tool < ~/.claude/settings.json` and
fix any syntax error it reports.

=========================================================
STEP 5 — Optional: enable live quota (skip if you don't know what this is)
=========================================================
The bar has a "⏱" segment that shows live quota for some providers.
It only appears if you route Claude Code through a third-party
gateway AND set that gateway's API key. Skip this step if you
use Claude Code directly (no gateway) — Anthropic doesn't expose
a per-account quota API.

If you DO use a gateway, ask me which one and add the matching env
var to my shell rc (~/.zshrc, ~/.bashrc, or ~/.profile):

  export MINIMAX_API_KEY=...        # for MiniMax Token Plan
  export OPENROUTER_API_KEY=...     # for OpenRouter credits
  export DEEPSEEK_API_KEY=...       # for DeepSeek balance
  export MISTRAL_API_KEY=...        # for Mistral usage
  export OPENAI_API_KEY=...         # for OpenAI admin credit grants

I will paste my actual key — never invent one. After I paste it,
restart Claude Code and verify the ⏱ segment appears.

=========================================================
STEP 6 — Optional: enable the 🌐 router segment
=========================================================
If I use the fcc-claude wrapper (you confirmed this in STEP 1), the
statusline will automatically show 🌐 http://localhost:<port> in soft
green. If the fcc-server proxy crashes, it flips to red — a quick
visual cue that something is wrong. No action needed; this works out
of the box.

=========================================================
DONE — Tell me what you did
=========================================================
Summarise in 3-5 bullet points:
- which install method you used
- the exact path to session_tokens.py on my machine
- the contents of my settings.json statusLine block
- whether STEP 4 verification passed
- any caveats or things I should know

If anything failed, give me the exact error message and the command
that produced it. Don't try to fix it silently — surface it.
```

</details>

### 1. Install

Pick **one** install method.

#### Symlink (recommended for development)

```bash
git clone https://github.com/philipecomputacao/claude-llm-quota-bar.git \
    ~/src/claude-llm-quota-bar

mkdir -p ~/.claude/statusline
ln -sf ~/src/claude-llm-quota-bar/session_tokens.py \
       ~/.claude/statusline/session_tokens.py
```

#### Direct copy (no symlink)

```bash
curl -fsSL https://raw.githubusercontent.com/philipecomputacao/claude-llm-quota-bar/main/session_tokens.py \
    -o ~/.claude/statusline/session_tokens.py
chmod +x ~/.claude/statusline/session_tokens.py
```

### 2. Wire it into Claude Code

Edit `~/.claude/settings.local.json` (or `~/.claude/settings.json` for the global one):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline/session_tokens.py"
  }
}
```

Restart Claude Code. You should see the new bar immediately.

### 3. (Optional) Set API keys for live quota

> **Native Claude Code sessions don't need any API key.** The `⏱` segment
> is only relevant when you route Claude Code through a third-party
> gateway that exposes its own quota API. Anthropic does not publish a
> per-account rate-limit endpoint, so the `⏱` segment is intentionally
> omitted for native Claude sessions.

The `⏱` segment only renders if the matching API key is set. Add to your shell rc:

```bash
# ~/.zshrc or ~/.bashrc
export MINIMAX_API_KEY=sk-cp-...           # MiniMax Token Plan
export OPENROUTER_API_KEY=sk-or-...         # OpenRouter credits
export DEEPSEEK_API_KEY=sk-...              # DeepSeek balance
export MISTRAL_API_KEY=ms-...               # Mistral usage
export OPENAI_API_KEY=sk-admin-...          # OpenAI credit grants (admin key)
```

Or in `~/.fcc/.env` (the script reads both — env vars win):

```bash
# ~/.fcc/.env
MINIMAX_API_KEY=sk-cp-...
OPENROUTER_API_KEY=sk-or-...
```

Providers without a key simply **omit** the `⏱` segment — no error, no noise.

### 4. (Optional) Customise the bar

Copy the bundled config to your home dir and edit:

```bash
cp statusline.env.json ~/.claude/statusline.env.json
$EDITOR ~/.claude/statusline.env.json
```

See [Configuration](#configuration) for the full list of options.

---

## Providers supported

The statusline renders cleanly for **any** model the active Claude Code session has
ever called. Pricing is read from `pricing.json` (402 models, 5 direct providers
+ openrouter gateway with hundreds of upstream models).

| Provider | Cost | Tokens | Cache R/W | Quota (`⏱`) |
|---|---|---|---|---|
| Claude (native) | ✅ | ✅ | ✅ | — ¹ |
| `minimax` | ✅ | ✅ | ✅ | **✅** (Token Plan 5h + weekly) |
| `open_router` | ✅ | ✅ | ✅ | **✅** (credits API) |
| `opencode` | ✅ | ✅ | ✅ | — (gateway) |
| `opencode_go` | ✅ | ✅ | ✅ | — (gateway) |
| `deepseek` | ✅ | ✅ | ✅ | **✅** (`/user/balance`) |
| `mistral` / `codestral` | ✅ | ✅ | ✅ | **✅** (`/v1/usage`) |
| `nvidia_nim` | ✅ | ✅ | ✅ | — |
| `gemini` | ✅ | ✅ | ✅ | — |
| `groq`, `cerebras`, `fireworks`, `zai` | ✅ | ✅ | ✅ | — |
| `kimi`, `wafer` | ✅ | ✅ | ✅ | — |
| `ollama`, `llamacpp`, `lmstudio` | ✅ | ✅ | ✅ | — (local) |
| OpenAI direct (`gpt-*`, `o1-*`, `o3-*`, `o4-*`) | ✅ | ✅ | ✅ | **✅** (admin key, credit grants) |
| ChatGPT via Codex (`gpt-*` + `codex login`) | ✅ | ✅ | ✅ | **✅** (plan badge) |

— = no live quota API; the `⏱` segment is omitted silently.
¹ Anthropic exposes no per-account rate-limit endpoint, so `⏱` is never shown for native Claude sessions.

---

## Quota adapters

Anthropic-native Claude Code sessions use no quota adapter — Anthropic
exposes no per-account rate-limit endpoint, so the `⏱` segment is
intentionally omitted for native sessions. The adapters below activate
only when Claude Code is routed through a third-party provider whose API
supports live quota introspection.

Six quota adapters are wired up. The bar shows a single `⏱` segment for the **active**
provider's adapter; the segment is omitted if no adapter matches.

| Provider | Endpoint | Auth | Format |
|---|---|---|---|
| `minimax` | `GET https://www.minimax.io/v1/token_plan/remains` | `MINIMAX_API_KEY` (env or `~/.fcc/.env`) | `⏱ 40% usado (60% livre) (reset 2h48m)` |
| `open_router` | `GET https://openrouter.ai/api/v1/credits` | `OPENROUTER_API_KEY` | `⏱ 25% usado (75% livre) ($2.50 used of $10.00)` |
| `deepseek` | `GET https://api.deepseek.com/user/balance` | `DEEPSEEK_API_KEY` | `⏱ $4.50 USD (usou $0.50 de $5.00 free)` |
| `mistral` | `GET https://api.mistral.ai/v1/usage` | `MISTRAL_API_KEY` | `⏱ 1.7M tokens (modelos: mistral-large-latest, mistral-small-latest)` |
| `openai_dashboard` | `GET https://api.openai.com/v1/dashboard/billing/credit_grants` | `OPENAI_API_KEY` (admin only) | `⏱ 12% usado (88% livre) ($12.00 used of $100.00)` |
| `codex_chatgpt` | reads `~/.codex/auth.json`, decodes JWT (no network) | `~/.codex/auth.json` or `$CODEX_ACCESS_TOKEN` | `⏱ Plus (80 msgs / 3h) (limite OpenAI pode mudar)` |

**Aliases:**
- `codestral` → `mistral` (the fcc-claude `codestral` gateway hits the same
  Mistral backend, so its usage shows up in Mistral's `/v1/usage`).

### Detection heuristic

The bar chooses the adapter using this priority chain:

1. **Gateway prefix** in the model id (`minimax/MiniMax-M3` → `minimax`)
2. **`provider` field** in the resolved pricing entry (`deepseek-v4-pro` → `deepseek`)
3. **Bare-model family heuristic** (e.g. `deepseek-v4-pro` without prefix → `deepseek`)
4. **Codex shape** + `~/.codex/auth.json` (valid JWT) → `codex_chatgpt`
5. **Codex shape** + `$OPENAI_API_KEY` (admin) → `openai_dashboard`
6. **No match** → segment omitted

The bare-model heuristic exists because fcc-claude routes many direct-provider models
through the `opencode`/`opencode_go` gateway in `pricing.json`. The heuristic catches
both the bare and gateway forms.

### Codex ChatGPT specifics

The `codex_chatgpt` adapter **does not** call the OpenAI API. It reads the JWT that
`codex login` saved in `~/.codex/auth.json` and decodes the
`https://api.openai.com/auth.chatgpt_plan_type` claim. This matches what the
`codex login status` command does internally (`codex-rs/login/src/token_data.rs`).

The plan rate-limits are a hardcoded table — OpenAI doesn't publish them and doesn't
expose subscription quota via the public API. The badge includes `(limite OpenAI pode
mudar)` to set expectations.

| Plan | Badge |
|---|---|
| `free` | `Free (3 msgs / 40h)` |
| `plus` | `Plus (80 msgs / 3h)` |
| `pro` | `Pro (500 msgs / 3h)` |
| `business` | `Business (100 msgs / 3h)` |
| `enterprise` | `Enterprise (1000 msgs / 3h)` |
| `edu` | `Edu (50 msgs / 3h)` |
| `team` | `Team (100 msgs / 3h)` |
| _other_ | `<key> (limite desconhecido)` |

---

## Colour rules

Three visual states are shared between the `⏱` quota segment, the `🧠` context
segment, the `⚡` burn rate, and the `R$` cost.

| Segment | 🟢 green | 🟡 yellow | 🔴 red |
|---|---|---|---|
| `⏱` quota used % | `< 60%` | `60–84%` | `≥ 85%` |
| `🧠` context used % | `< 70%` | `70–89%` | `≥ 90%` |
| `⚡` burn rate | `< 15k t/m` (or 150k for 1M-context models) | mid | `≥ 50k t/m` (or 500k) |
| `R$` cost in BRL | `< R$ 0.50` | `R$ 0.50–2.49` | `≥ R$ 2.50` |
| `🔀` git dirtyness | `0 lines` (clean) | `50–299 lines` pending | `≥ 300 lines` pending |

The quota thresholds **changed in 2026-06**: we now show the **used** percentage
(more intuitive: bigger = worse) and the alert kicks in at **85%**, not 90%. If
you prefer the old 70/90 cutoffs, override in `~/.claude/statusline.env.json`:

```json
{
  "quota_warn_pct": 70,
  "quota_alert_pct": 90
}
```

All other thresholds live in `lib/display.py::DisplayOptions` and are also
overridable via the env file.

### Disable colours

Set `"color": "never"` in your config — same effect as piping to `less -R` or
sending the bar to a log file.

---

## Router segment (🌐)

A 🌐 marker is rendered at the end of the cost line so the user can
tell at a glance whether the active session is going through a local
proxy (like `fcc-claude`/`fcc-server`) or straight to the official
Anthropic API. The URL is read from `ANTHROPIC_BASE_URL` on every tick
(5s) — no caching, no daemon, no extra subprocess.

### Three visual states

| State | Colour | Trigger |
|---|---|---|
| `🌐 http://localhost:<port>` | Soft green (`DIM + GREEN`) | `ANTHROPIC_BASE_URL` points at a local host AND the proxy answered the last health probe (`"ok"`). |
| `🌐 http://localhost:<port>` | Red | Same URL but the health probe reported `"down"` (TCP refused, timeout). |
| `🌐 router desativado` | Grey | `ANTHROPIC_BASE_URL` unset or points at `api.anthropic.com` — vanilla Claude Code. |

The health probe is **skipped entirely** for non-local URLs (we don't
ping `api.anthropic.com` on every tick) and when `show_router` is
disabled — both cases return `"ok"` so the segment keeps its default
colour without a network round-trip.

### Health probe (HEAD)

The verdict comes from `lib/router_health.py`, a single HEAD request
(`urllib.request`, stdlib only) to `ANTHROPIC_BASE_URL` with:

- **1.0 s timeout** — long enough to absorb a slow TCP handshake, short
  enough to keep the statusline responsive even when the proxy is
  frozen.
- **45 s in-memory cache** — at the default 5 s refresh tick, the user
  sees at most one stale verdict between probes. Tunable via
  `router_health_ttl_seconds` in `statusline.env.json` (set to `0` to
  probe every tick).
- **Thread-safe** — a module-level lock serialises the cache-miss path
  so bursty ticks can't fire redundant HEADs.
- **Verdicts** — `ok` (any HTTP response, including 404 on `/` — the
  typical reply from a reverse proxy that only forwards specific
  paths), `down` (TCP refused / timeout / DNS failure), `unknown`
  (SSL error etc., falls back to the default colour so we don't
  false-alarm).

The check costs ~12 ms on a cache miss and <1 ms on a cache hit. A
frozen proxy adds 1.0 s to a single tick per 45-second window — well
within the 5 s refresh budget.

### Config

```json
{
  "show_router":              true,  // render the segment at all
  "show_router_health":       true,  // run the HEAD probe
  "router_health_ttl_seconds": 45    // cache window for the verdict
}
```

---

## Configuration

The bundled `statusline.env.json` documents every option. To override, copy it to
`~/.claude/statusline.env.json` and edit. **All keys are optional**; missing keys
fall back to the defaults in `lib/display.py::DisplayOptions`.

```json
{
  "_comment": "Custom display toggles for the Claude Code statusline.",

  "show_provider":      true,   // model label on line 1
  "show_model":         true,   // model name on line 1
  "show_tokens":        true,   // ⬆ ⬇ ↻R on line 2
  "show_cost":          true,   // 🇧🇷 R$ / 🇺🇸 $ on line 3
  "show_duration":      true,   // ⌛ wall-clock duration
  "show_burn_rate":     true,   // ⚡ tokens/minute
  "show_cache_pct":     true,   // cache hit ratio
  "show_flags":         true,
  "show_both_currencies": true, // show 🇧🇷 + 🇺🇸 side by side
  "show_provider_quota":   true, // ⏱ live quota segment
  "show_router":            true, // 🌐 router segment on cost line
  "show_router_health":     true, // HEAD probe for local proxy health
  "router_health_ttl_seconds": 45, // cache window for the verdict (0 = every tick)

  "quota_warn_pct":  60,        // yellow at 60% quota used
  "quota_alert_pct": 85,        // red    at 85% quota used

  "git_dirty_warn_lines": 50,   // yellow at 50 lines pending
  "git_dirty_alert_lines": 300, // red   at 300 lines pending

  "cost_warn_brl":   0.50,
  "cost_alert_brl":  2.50,
  "burn_warn_per_min": 15000,   // 150k for 1M-context models
  "burn_alert_per_min": 50000,  // 500k for 1M-context models

  "fx_cache_ttl_seconds": 3600, // refresh BRL/USD every 1h
  "verbose":          false,    // show extra debug fields
  "color":            "auto"    // "auto" | "always" | "never"
}
```

### Pricing data

`pricing.json` ships with **402 models across 5 direct providers** plus a gateway
pass-through to OpenRouter's full catalogue. To add a new model:

```json
{
  "models": {
    "your-provider/your-model-name": {
      "provider":  "your-provider",
      "display":   "Your Model",
      "input":     0.55,        // USD per 1M input tokens
      "output":    2.20,        // USD per 1M output tokens
      "cache_read": 0.055,      // USD per 1M cache-read tokens (optional)
      "cache_write": 0.55,      // USD per 1M cache-write tokens (optional)
      "unit":      "per_million_tokens",
      "billing_mode": "pay_as_you_go",
      "tier":      "qwen-medium" // grouping tier (informational)
    }
  }
}
```

Missing pricing entries fall back to the `__fallback__` row and the bar shows `?`
for that model — the script does **not** crash.

### FX (USD ↔ BRL) rates

The script fetches the BRL/USD rate from `https://open.er-api.com/v6/latest/USD`
(50 reqs/month free tier), caches the result in
`~/.cache/claude-llm-quota-bar/fx.json` for `fx_cache_ttl_seconds` (default 1h),
and falls back to a static 5.20 if the API is unreachable.

---

## How it works

```
┌────────────────────┐  stdin (JSON)   ┌────────────────────┐
│  Claude Code TUI   │ ───────────────► │  session_tokens.py │
└────────────────────┘                  └──────────┬──────────┘
       ▲                                          │
       │ renders 5 lines                          │ reads
       │                                          ▼
       │                                  ~/.claude/projects/<hash>/
       │                                  <sessionId>.jsonl
       │                                          │
       │                              ┌───────────┴───────────┐
       │                              ▼                       ▼
       │                      pricing.json             lib/provider_quota.py
       │                      (402 models)            (6 quota adapters)
       │                                          lib/router_health.py
       │                                          (HEAD probe, 45s cache)
       │                              │                       │
       │                              └───────────┬───────────┘
       │                                          ▼
       │                              5 lines: dir / id+bookmark / tokens /
       │                              cost / git
       └──────────────────────────────────────────┘
```

**Flow per render** (called by Claude Code at `statusLine.refreshInterval`,
default 5 s — and immediately after each model response):

1. **Stdin parse** — Claude Code pipes a JSON payload with model id, working dir,
   version, and the cumulative session cost
2. **CWD resolution** — layered fallback: `CLAUDE_PROJECT_DIR` env → on-disk cache
   (1h TTL) → `lsof` discovery (macOS) → placeholder. Keeps the bar working when
   Claude Code forgets to export the env var.
3. **JSONL aggregate** — the script reads `~/.claude/projects/<hash>/<sessionId>.jsonl`,
   sums `input_tokens` / `output_tokens` / `cache_read_input_tokens` /
   `cache_creation_input_tokens` across all `assistant` messages in the session.
   Result is cached for 2 s (keyed on mtime+size) so consecutive render ticks reuse
   the parsed aggregate.
4. **Git metadata** — `lib/git.py` runs up to 4 `git` subprocesses on the resolved
   cwd: branch, short hash, commit subject, and `diff HEAD --numstat` for
   working-tree dirtyness. Each call is bounded by a 1.5 s timeout and falls back
   silently to `None` / `0`.
5. **Pricing lookup** — resolves the model id (with gateway-prefix stripping) to a
   `ModelPrice` entry, computes the cost in USD, converts to BRL using the cached FX
6. **Router segment** — read `ANTHROPIC_BASE_URL` (cheap env lookup, no I/O). If it
   points at a local host, call `lib/router_health.py:check_router` for a verdict
   (HEAD probe with 1.0 s timeout, 45 s in-memory cache). The result lands as the
   🌐 segment at the end of the cost line. Skipped entirely for non-local URLs and
   when `show_router` is disabled.
7. **Quota lookup** — for the active provider, calls the matching `QuotaProvider.fetch()`
   in `lib/provider_quota.py`. Each adapter handles its own auth, retry, and caching
8. **Render** — `render()` in `lib/display.py` builds 5 lines:
   `📁 cwd` · `[model·provider] 📟 version 🔖 bookmark` ·
   `⬆⬇↻ ⏱ quota 🧠 context` · `🇧🇷 R$ 🇺🇸 $ ⌛ duration ⚡ burn 🌐 router` ·
   `🔀 branch • hash • title • +N/-M`

The script is **stateless** — every render reads from disk. This makes it safe to
restart Claude Code mid-session without losing state.

---

## Adding a new provider

To add support for a new provider (pricing only, no quota adapter):

1. **Add entries to `pricing.json`** for the provider's models. Use the schema
   shown in [Pricing data](#pricing-data).
2. **(Optional) Add a heuristic in `session_tokens.py::_direct_provider_for_bare_model`**
   if the provider ships bare model names (no gateway prefix) that should be
   detected from the model id alone.
3. **(Optional) Add a `provider_id` mapping** if the provider's id in pricing.json
   doesn't match the one you want users to see in the bar.
4. Run `python3 session_tokens.py` with a test payload to verify the bar.

That's it — no code changes needed for pricing-only support.

---

## Adding a new quota adapter

To add a live quota adapter (e.g. for a new provider with a public quota API):

1. **Implement the adapter** in `lib/provider_quota.py`:

   ```python
   class MyProviderQuotaProvider:
       provider_id = "my_provider"

       def fetch(
           self,
           api_key: str | None = None,
           *,
           cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
           cache_path: Path | None = None,
           now: float | None = None,
       ) -> QuotaInfo:
           # Read API key from env / ~/.fcc/.env
           api_key = api_key or os.environ.get("MY_PROVIDER_API_KEY")
           if not api_key:
               return QuotaInfo(
                   provider_id=self.provider_id,
                   status_label="error",
                   source="error",
                   error="MY_PROVIDER_API_KEY not set",
               )

           # Read cache first
           cached = _read_cache(cache_path, cache_ttl_seconds)
           if cached and self.provider_id in cached:
               return cached[self.provider_id]

           # Call the upstream API
           status, body = _request_json(
               "https://api.my-provider.com/v1/quota",
               headers={"Authorization": f"Bearer {api_key}"},
           )
           if status != 200:
               return QuotaInfo(
                   provider_id=self.provider_id,
                   status_label="error",
                   source="error",
                   error=f"upstream HTTP {status}: {str(body)[:120]}",
               )

           # Parse and return
           used_pct = body["used"] / body["limit"] * 100
           return QuotaInfo(
               provider_id=self.provider_id,
               status_label=f"{used_pct:.0f}% usado ({100 - used_pct:.0f}% livre)",
               detail=f"{body['used']:,} of {body['limit']:,}",
               used_pct=used_pct,
               source="live",
           )
   ```

2. **Register it** in `QUOTA_PROVIDERS`:

   ```python
   QUOTA_PROVIDERS: dict[str, QuotaProvider] = {
       "minimax":          MinimaxQuotaProvider(),
       "open_router":      OpenRouterQuotaProvider(),
       "codex_chatgpt":    CodexChatgptQuotaProvider(),
       "deepseek":         DeepSeekQuotaProvider(),
       "openai_dashboard": OpenAIDashboardQuotaProvider(),
       "mistral":          MistralQuotaProvider(),
       "my_provider":      MyProviderQuotaProvider(),  # ← new
   }
   ```

3. **(Optional) Add detection heuristic** in `session_tokens.py` so the bar
   activates the adapter for matching model ids without manual config.

4. **Update `pricing.json`** so the provider id resolves correctly (the adapter
   detection chain reads `price.provider` second after gateway-prefix parsing).

5. **Update this README** with the new entry in [Quota adapters](#quota-adapters).

---

## Troubleshooting

### `⏱` segment is missing

The `⏱` segment is omitted silently if:
- the active model doesn't match any provider with a quota adapter
- the matching API key isn't in the env or `~/.fcc/.env`
- the upstream returned a non-200 response (e.g. 401, 403, 404)
- the upstream returned a payload the adapter doesn't recognise

To diagnose, run the script directly with `verbose: true` in your config and watch
the JSONL output for `[<provider>] <error>` lines.

### Stale quota data

The cache TTL is 60s. To force a refresh:

```bash
rm ~/.cache/claude-llm-quota-bar/provider-quota.json
```

### `???` model label

Means the model id isn't in `pricing.json` and the `__fallback__` row is being used.
Add an entry — see [Pricing data](#pricing-data).

### Cost seems wrong

Check the BRL/USD FX rate cache:

```bash
cat ~/.cache/claude-llm-quota-bar/fx.json
```

If `source: "fallback"`, the API call failed and we're using a hardcoded 5.20.
Otherwise the rate is fresh (within `fx_cache_ttl_seconds`).

### Bar doesn't appear at all

Verify the script is callable:

```bash
python3 ~/.claude/statusline/session_tokens.py < /dev/null
# Should exit 0 with empty stdout

CLAUDE_PROJECT_DIR="$PWD" CLAUDE_SESSION_ID=test \
    python3 ~/.claude/statusline/session_tokens.py < /dev/null
# Should exit 0 with empty stdout (no JSONL yet)
```

Then trigger any prompt in Claude Code and check the bar.

### `ANTHROPIC_API_KEY` doesn't enable the `⏱` segment

Anthropic does not expose a per-account rate-limit or quota API. Setting
`ANTHROPIC_API_KEY` is **not** enough to make the `⏱` segment appear for
native Claude sessions — it is silently ignored as a quota key. To see live
quota, route Claude Code through a third-party gateway (e.g. MiniMax,
OpenRouter) and set that gateway's key (`MINIMAX_API_KEY`,
`OPENROUTER_API_KEY`, etc.).

### `MINIMAX_API_KEY not set` (or similar)

The script reads keys from both the env and `~/.fcc/.env`. Verify the file exists
and the key line matches `^MINIMAX_API_KEY=...$` (no leading `export `, no quotes
unless you escape them).

### `Cache` reads always 0

Cache reads only show if the upstream supports prompt caching (Anthropic, OpenAI,
DeepSeek, etc.) **and** the request actually hit a cached prefix. New sessions
always start with `↻R 0`.

---

## Development

```bash
git clone https://github.com/philipecomputacao/claude-llm-quota-bar.git
cd claude-llm-quota-bar

# Run the script in isolation
python3 session_tokens.py < /dev/null

# Render with a mock JSONL session
python3 -c "
import json
from pathlib import Path
import os
session_id = 'dev-test'
project_dir = os.getcwd()
hash_id = project_dir.replace('/', '-')
path = Path.home() / '.claude/projects' / hash_id / f'{session_id}.jsonl'
path.parent.mkdir(parents=True, exist_ok=True)
with open(path, 'w') as f:
    f.write(json.dumps({
        'type': 'assistant',
        'sessionId': session_id,
        'timestamp': '2026-06-20T13:00:00.000Z',
        'message': {
            'role': 'assistant',
            'model': 'anthropic/minimax/MiniMax-M3',
            'usage': {
                'input_tokens': 1234, 'output_tokens': 567,
                'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
            }
        }
    }) + '\n')
print(f'wrote {path}')
"
CLAUDE_PROJECT_DIR="$PWD" CLAUDE_SESSION_ID=dev-test \
    python3 session_tokens.py < /dev/null
# Should render the bar
```

### Project layout

```
.
├── session_tokens.py        # main entry point
├── lib/
│   ├── display.py           # ANSI colour rules + render pipeline
│   ├── parser.py            # JSONL aggregator + token totals
│   ├── pricing.py           # pricing.json loader + cost compute
│   ├── provider_quota.py    # 6 QuotaProvider adapters + registry
│   ├── fx.py                # BRL/USD FX rate cache
│   ├── git.py               # git metadata resolver (branch, commit, dirtyness)
│   └── router_health.py     # HEAD-based local proxy health probe (1.0s timeout, 45s cache)
├── scripts/
│   └── new_window.sh        # macOS helper: open a new Terminal that resumes a session
├── pricing.json             # 402 models, 5 direct providers
├── statusline.env.json      # default display toggles
└── .github/workflows/
    └── ci.yml               # py_compile + smoke test
```

### Tests

The script has no unit tests (the integration surface is Claude Code itself). All
adapters have **mock-based smoke tests** baked into the file's `if __name__ == "__main__"`
block — see `lib/provider_quota.py` for examples.

### Lint / type-check

```bash
# No third-party deps needed; uses stdlib only
python3 -m py_compile session_tokens.py
python3 -m py_compile lib/*.py
```

---

## Related projects

- **[free-claude-code-minimax][fcc]** — the fcc-claude fork that this project was
  originally built for. Adds `minimax` as a first-class provider.

[fcc]: https://github.com/philipecomputacao/free-claude-code-minimax

---

## Upstream history

This project was originally forked from
[Miluer-tcq/cc-statusline](https://github.com/Miluer-tcq/cc-statusline) but
is now fully independent. The upstream was rewritten in bash + JSON presets
in 2025; we intentionally stayed on Python 3 so we can add new quota
adapters without maintaining bash. A weekly GitHub Action used to open
tracking issues when upstream gained new commits, but the divergence
tracker was removed in v2.1.0 since the two codebases no longer share
edits in any meaningful way. See [CHANGELOG.md](CHANGELOG.md) for the
historical timeline.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Security

This repo never contains real API keys — see [SECURITY.md](SECURITY.md)
for the full policy and runtime cache contents.

## Documentation

- [README.md](README.md) — this file
- [CLAUDE.md](CLAUDE.md) — entry points, dev commands, naming conventions
  for future Claude Code agents working on this repo
- [SECURITY.md](SECURITY.md) — secret-handling policy + audit log
- [CONTRIBUTING.md](CONTRIBUTING.md) — bug reports, feature requests,
  how to add a new quota adapter
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1
- [SUPPORT.md](SUPPORT.md) — where to ask questions
- [CHANGELOG.md](CHANGELOG.md) — release notes

---

Curadoria e desenvolvimento por **[@lpdigital.me](https://www.instagram.com/lpdigital.me/)**.
