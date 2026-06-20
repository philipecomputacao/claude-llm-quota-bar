# CLAUDE.md

Project-specific notes for Claude Code agents working on this repo.

The user-level conventions (commit style, HTML preference, secrets policy,
central-projetos layout) live at `~/Projetos/AGENTS.md` — read that first.

---

## Purpose

`claude-llm-quota-bar` is a single-file Python 3 statusline script
(`session_tokens.py`) for Claude Code. On every refresh tick Claude Code
pipes a JSON payload to the script; the script reads the session JSONL,
aggregates token usage, computes cost from `pricing.json`, optionally
calls a live quota API for the active provider, and renders a 3-line
colour-coded bar. The project is pure stdlib (no `requests`, no
`pydantic`) and intentionally small: 4 lib files + 1 entry point + 1
JSON data file. The differentiator vs Claude Code's built-in statusline
is multi-provider live quota tracking — 18+ providers with pricing, 6
with live quota adapters (`minimax`, `open_router`, `codex_chatgpt`,
`deepseek`, `openai_dashboard`, `mistral`).

---

## Entry points & key modules

Read in this order when investigating:

1. **`session_tokens.py`** — CLI entry, stdin parsing, JSONL tail-aggregate,
   dispatch to display. Look here for the main flow.
2. **`lib/parser.py`** — JSONL aggregator + provider-prefix detection.
   Gateway prefixes (`minimax/`, `anthropic/`, `claude-3-freecc-no-thinking/`)
   are stripped here to recover the real upstream provider id.
3. **`lib/pricing.py`** — `pricing.json` loader + cost compute.
4. **`lib/provider_quota.py`** — 6 `QuotaProvider` adapters + the
   `QUOTA_PROVIDERS` registry. The Protocol each adapter implements is
   at `lib/provider_quota.py:67-80` (only `provider_id` + `fetch()`,
   no `applies_to`/`parse` — **do not** trust the old skeleton that
   used to live in `CONTRIBUTING.md`; it's been corrected).
5. **`lib/display.py`** — ANSI colour rules + render pipeline.
6. **`lib/fx.py`** — BRL/USD FX rate cache.
7. **`scripts/build_pricing.py`** — regenerates `pricing.json` from
   upstream pricing tables. Use `--diff` mode to preview changes.
8. **`pricing.json`** — 402 models. **Do not edit by hand** — re-run the
   build script instead.

The runtime cache lives at `~/.cache/claude-llm-quota-bar/` and contains
two files: `provider-quota.json` (quota percentages + reset times) and
`fx.json` (BRL/USD rate). Neither contains secrets.

---

## Dev commands

The project uses **no third-party deps** — stdlib only.

```bash
# Compile (matches CI step at .github/workflows/ci.yml)
python3 -m py_compile session_tokens.py
python3 -m py_compile lib/parser.py
python3 -m py_compile lib/display.py
python3 -m py_compile lib/fx.py
python3 -m py_compile lib/pricing.py
python3 -m py_compile lib/provider_quota.py
python3 -m py_compile scripts/build_pricing.py

# Run the script in isolation (renders placeholder)
python3 session_tokens.py < /dev/null

# Render with a mock JSONL session (see README § Development for the
# full snippet — it builds a fake JSONL with the gateway-prefixed
# model id 'anthropic/minimax/MiniMax-M3' and invokes with
# CLAUDE_PROJECT_DIR / CLAUDE_SESSION_ID set)

# Audit for accidentally-committed secrets (should always return zero)
git grep -niE 'sk-(cp|or|admin)?-[a-zA-Z0-9_-]{20,}'
```

CI runs `py_compile` + a smoke test with all quota env vars blanked
(`MINIMAX_API_KEY=""` etc.) — the script must short-circuit on the
no-key path without crashing. The CI workflow is at
`.github/workflows/ci.yml`.

---

## Naming conventions & what NOT to touch

These strings are part of the **runtime public contract** — renaming
any of them breaks existing user setups silently (the cache file from
a prior version no longer matches the new keys).

| Constant | Where it lives | Why it's stable |
|---|---|---|
| `provider_id` values (`"minimax"`, `"open_router"`, `"codex_chatgpt"`, `"deepseek"`, `"openai_dashboard"`, `"mistral"`) | `lib/provider_quota.py` class attrs + `QUOTA_PROVIDERS` registry keys + `~/.cache/claude-llm-quota-bar/provider-quota.json` cache keys + `pricing.json` `provider` field | Cache and pricing lookup both read by id; renaming orphans existing data |
| Env var names: `MINIMAX_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`, `OPENAI_API_KEY`, `CODEX_ACCESS_TOKEN` | read in `lib/provider_quota.py` adapters + referenced in docs | Users have them in `~/.zshrc` and `~/.fcc/.env`; renaming silently breaks `⏱` |
| `CACHE_DIRNAME = "claude-llm-quota-bar"` | `lib/fx.py`, `lib/provider_quota.py` | Was renamed **once** (commit `74cf3e9`) — do not rename again |
| Gateway prefixes `anthropic/` and `claude-3-freecc-no-thinking/` | `lib/parser.py:125-128` (gateway prefix stripping) | Part of the fcc-claude contract; if you change them, fcc-claude users' model ids stop resolving |
| `QuotaProvider` Protocol shape (`provider_id` + `fetch()` → `QuotaInfo`) | `lib/provider_quota.py:67-80` | All adapters implement this; changing it is a multi-file refactor |

If you need to add a new provider, follow the order in
`CONTRIBUTING.md § "Adding a new quota adapter"`:

1. Add `pricing.json` entries (or re-run `scripts/build_pricing.py`).
2. Optionally add a heuristic in `session_tokens.py::_direct_provider_for_bare_model`.
3. Implement the `QuotaProvider` Protocol in `lib/provider_quota.py`.
4. Register in `QUOTA_PROVIDERS`.
5. Add a smoke test in the same file's `if __name__ == "__main__":` block.
6. Update `README.md` + `CONTRIBUTING.md` + `CHANGELOG.md`.

---

## Commit style & PR etiquette

- **Conventional Commits-lite in PT-BR**: `feat(scope):`, `fix(scope):`,
  `docs(scope):`, `refactor(scope):`, `chore:`, `tune(scope):`. The
  breaking-change prefix `docs!:` was used once (commit `74cf3e9`, the
  project rename).
- **End every commit message with**:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **PR template** (`.github/pull_request_template.md`) has a security
  checklist that's enforced: no real API keys in the diff, no env var
  that holds secrets, no logged tokens.
- **Never** rename an env var or `provider_id` in a docs-only pass —
  those are code/runtime contracts and need a coordinated migration.

---

## Visibility & status

- Repository visibility is **private** as of v2.1.0.
- The first tag is `v2.1.0` (semver). Future tags: bump minor on
  feature additions, patch on adapter fixes, major on env var or
  provider_id renames (coordinated migration required).
