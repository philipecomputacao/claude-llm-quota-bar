# Changelog

All notable changes to `llm-quota-bar` are documented here. The format is
loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with
versions grouped by date.

## [Unreleased]

### Planned
- (no items yet)

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
- **Audited `~/.cache/llm-quota-bar/`** — only public quota percentages
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
  - `openai_codex` — JWT-decode plan badge (Plus / Pro / Team)
- **`provider-quota.json`** cache at `~/.cache/llm-quota-bar/` (public
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