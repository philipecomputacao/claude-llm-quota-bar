# Changelog

All notable changes to `claude-llm-quota-bar` are documented here. The format is
loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with
versions grouped by date.

## [Unreleased]

### Fixed
- **Display: strip gateway suffixes from the model label.** The statusline
  no longer renders the pricing/roteamento metadata in parentheses —
  e.g. `deepseek-v4-pro (opencode_go)` now shows as `deepseek-v4-pro·deepseek`
  (upstream direct provider appended instead). The `pricing.json` `display`
  field is untouched — only the rendered statusline is cleaned up. The
  known-gateway list (`opencode_go` / `opencode` / `open_router`) is
  centralised in `lib/display.py:_GATEWAY_DISPLAY_LABELS`; upstream labels
  like `(minimax)` are kept as-is.
- **Display: always append the upstream direct provider to the label** when
  the parser resolves it (i.e. when `last_provider` is one of `deepseek` /
  `mistral` / etc. — never for `anthropic` / `unknown`). The previous
  substring-match heuristic was skipping the append whenever the model name
  happened to contain the provider string (e.g. `deepseek-v4-pro` showed
  without the `·deepseek` suffix), hiding the provider info. The label now
  always carries the provider when it is known.
- **Pricing: strip inherited `anthropic/` prefix from `ModelPrice.display`.**
  The 16 `open_router/anthropic/*` entries in `pricing.json` (e.g.
  `claude-fable-5`, `claude-opus-4.7`) had `display = "anthropic/claude-..."`
  because the fcc-claude gateway inherits the upstream native-Anthropic id
  when routing native-shaped models through OpenRouter. The prefix is
  misleading on the statusline — it reads like "this is an Anthropic-native
  model" when in fact it was routed through `open_router`. The strip happens
  in `lib/pricing.py:_entry_to_price` (data-layer fix), so every consumer of
  `ModelPrice.display` sees a clean label. The `pricing.json` file is
  untouched; the strip is applied at load time.

### Planned
- (no items yet)

---

## [2.1.0] — 2026-06-20

### Changed
- **Renamed the project from `llm-quota-bar` to `claude-llm-quota-bar`** to
  make the Claude Code target explicit in the repo name. GitHub redirects
  from the old URL are automatic. The runtime cache directory moved from
  `~/.cache/llm-quota-bar/` to `~/.cache/claude-llm-quota-bar/` — existing
  cache files are orphaned but regenerate on the next statusline run.
- **Docs rewritten as Anthropic/Claude-first.** README, SECURITY,
  CONTRIBUTING, CHANGELOG, and issue templates now lead with the native
  Claude Code happy path and present the third-party quota adapters
  (MiniMax, OpenRouter, DeepSeek, Mistral, OpenAI, Codex ChatGPT) as an
  extension. Provider support is **unchanged** — all six adapters remain
  wired and the `MINIMAX_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`,
  `MISTRAL_API_KEY`, `OPENAI_API_KEY`, `CODEX_ACCESS_TOKEN` env vars keep
  their names (they are public contract; renaming would silently break
  existing user setups).
- **Dropped the upstream-watcher.** `.github/upstream-sha` (empty) and
  `.github/workflows/watch-cc-statusline-upstream.yml` are removed — the
  divergence tracker hasn't fired usefully since the upstream was rewritten
  in bash. README's "Upstream divergence" section is replaced by a
  historical note pointing here.
- **Fixed historical CHANGELOG entry** under `[2026-05-30]`: the Codex
  ChatGPT adapter key is `codex_chatgpt`, not `openai_codex` (the adapter
  is at `lib/provider_quota.py:697` with `provider_id = "codex_chatgpt"`).
- **Fixed `CONTRIBUTING.md` adapter skeleton** to match the real
  `QuotaProvider` Protocol at `lib/provider_quota.py:67-80` (the old
  skeleton referenced a non-existent `QuotaStatus` dataclass and
  `applies_to()` / `parse()` methods — the real Protocol exposes only
  `provider_id` and `fetch()`, returning a `QuotaInfo` dataclass).

### Added
- **`CLAUDE.md`** — entry points, dev commands, naming conventions, and
  commit style for future Claude Code agents working on this repo. Required
  by the user's central `AGENTS.md`.
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1.
- **`SUPPORT.md`** — pointer to Discussions tab, issue templates, and the
  private security disclosure email.
- **`.github/description`** — one-line repo About text. Synced to GitHub
  via `gh repo edit --description`.
- **Troubleshooting note** in README: "`ANTHROPIC_API_KEY` doesn't enable
  the `⏱` segment" — Anthropic exposes no per-account quota API, so this
  env var is silently ignored as a quota key.

---

## [2026-06-20] — Audit + polish pass

### Added
- **`SECURITY.md`** — full security policy: what the repo contains, what
  gets cached at runtime, what NEVER will be in the repo, instructions
  for if you leak a key, audit log.
- **`CONTRIBUTING.md`** — bug reports, feature requests, "how to add a
  new quota adapter", style guide.
- **`CHANGELOG.md`** — this file.
- **README badges**: claude-code, models-402.
- **README "Highlights"** section — one-glance summary for陌生人 landing
  on the repo.

### Changed
- **`.gitignore`** — added `node_modules` (no slash) above the existing
  `node_modules/` rule to cover the dev-time symlink layout.

### Security
- **Audited every blob in full git history** for `sk-*`, `sk-or-*`,
  `sk-cp-*`, `sk-admin-*`, `ms-*` patterns — **zero leaks**.
- **Audited `~/.cache/claude-llm-quota-bar/`** — only public quota percentages
  and reset times; no tokens, no request bodies, no credentials.
- **Audit log entry** added to `SECURITY.md`.

---

## [2026-06-10] — Project rename

### Changed
- Renamed the project from `claude-code-statusline` to `llm-quota-bar` to
  better reflect its multi-provider nature (MiniMax, OpenRouter, DeepSeek,
  Mistral, OpenAI, Codex).
- Updated `README.md`, `lib/`, `scripts/build_pricing.py` paths.

---

## [2026-05-30] — Multi-provider quota adapters

### Added
- **`lib/provider_quota.py`** — generic `QuotaProvider` adapter pattern
  with 6 concrete adapters:
  - `minimax` — `GET /v1/token_plan/remains` (5h reset window)
  - `open_router` — `GET /api/v1/credits` (USD credits)
  - `deepseek` — `GET /user/balance` (USD balance)
  - `mistral` — `GET /v1/usage` (per-model tokens)
  - `openai_dashboard` — `GET /v1/dashboard/billing/credit_grants`
    (admin-only)
  - `codex_chatgpt` — JWT-decode plan badge (Plus / Pro / Team)
- **`provider-quota.json`** cache at `~/.cache/claude-llm-quota-bar/` (public
  data only — no keys, no request bodies).
- **Quota label format**: `X% usado (Y% livre)` matching the `🧠`
  context-window segment.
- **Colour thresholds**: 60% warn (yellow), 85% alert (red).

### Changed
- Statusline now renders the `⏱` segment whenever a matching API key is
  set; falls back to a greyed-out `⏱ —` otherwise (no crash).

---

## [2026-05-12] — `pricing.json` rebuild

### Added
- **`pricing.json`** — 402 models, 5 direct providers (Anthropic, OpenAI,
  Google, Mistral, DeepSeek) plus aliases for 13+ gateway IDs.
- **`scripts/build_pricing.py`** — regenerates `pricing.json` from the
  upstream pricing tables; ships a `--diff` mode to surface only changed
  entries.

---

## [2026-05-01] — Statusline rewrite to Python 3

### Changed
- Migrated the statusline core from bash to Python 3 (stdlib only —
  no `requests`, no `pydantic`).
- Three-line bar layout:
  - line 1: `[model·provider] • 📁 cwd • 📟 cc_version`
  - line 2: `⬆ input ⬇ output ↻R cache-read • ⏱ quota • 🧠 ctx`
  - line 3: `🇧🇷 R$ BRL  🇺🇸 $ USD • ⌛ duration • ⚡ burn rate`

### Added
- **`lib/parser.py`** — JSONL aggregator with per-session + cross-session
  totals, tolerance for missing fields.
- **`lib/display.py`** — ANSI colour rules + render pipeline.
- **`lib/fx.py`** — BRL/USD FX rate with 1-hour cache.
- **Burn rate emoji tiers** (`🧊` / `⚡` / `🔥`).
- **Cache read** as a separate `↻R` green segment (was lumped with input).

### Removed
- The upstream bash implementation (we intentionally stay on Python 3 so
  we can add new quota adapters without maintaining bash).