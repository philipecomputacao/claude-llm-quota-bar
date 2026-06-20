# Security policy

This document covers how `claude-llm-quota-bar` handles secrets.

## TL;DR

**No real API keys live in this repo.** They never have, and the policy is
that they never will. Keys live in your shell env or `~/.fcc/.env` and are
referenced by name only.

**Note on Anthropic:** Anthropic does not expose a per-account rate-limit or
quota API. Native Claude Code sessions therefore have no `⏱` live-quota
segment; the script falls back to graceful omission. If you route Claude
Code through a third-party gateway (MiniMax, OpenRouter, etc.), set that
gateway's API key instead — `ANTHROPIC_API_KEY` alone will not enable the
`⏱` segment.

## What the repo contains

| Item | Contains secrets? |
|---|---|
| `session_tokens.py` | ❌ References `MINIMAX_API_KEY` etc. by env var name only |
| `lib/provider_quota.py` | ❌ Reads from `os.environ` + `~/.fcc/.env` |
| `pricing.json` | ❌ Public price table |
| `~/.cache/claude-llm-quota-bar/` (runtime) | ❌ Public output only — see "What gets cached" below |

## What gets cached at runtime

The statusline writes two files under `~/.cache/claude-llm-quota-bar/`:

1. **`provider-quota.json`** — quota percentages and reset times only:
   ```json
   {
     "_fetched_at": 1781989062.69,
     "entries": {
       "minimax": {
         "status_label": "24% usado (76% livre)",
         "detail": "reset 3h2m",
         "used_pct": 24.0,
         "fetched_at": 1781989062.69
       }
     }
   }
   ```
   **No tokens, no request bodies, no credentials.**
2. **`fx.json`** — BRL/USD FX rate (refreshed hourly, cached 1h). Public data.

None of these files contain keys. The `.gitignore` template in the central
excludes `.cache/`, `.env*`, `*.key`, `credentials*.json`, etc.

## What this repo will NEVER contain

- Real API keys (`sk-*`, `sk-or-*`, `sk-cp-*`, `ms-*`, etc.)
- Real OAuth client secrets (`client_secret*.json`, `*-credentials.json`)
- Production `.env` files
- Live quota tokens, session cookies, or JWTs
- n8n workflows with real credentials (`n8n-workflow.json`)

For example secrets used in dev tooling, see `scripts/build_pricing.py`
— it uses obviously-fake values (`sk-test-...`, `sk-cp-EXAMPLE`).

## If you leak a key

1. **Rotate it immediately** at the provider's dashboard (do this before
   anything else — leaked keys can be drained in seconds).
2. **BFG Repo-Cleaner** or `git filter-repo` to scrub from history if you
   pushed before realising.
3. **Force-push** the cleaned history (only safe if you're the only
   collaborator — otherwise coordinate).
4. **Open an issue** with the provider if you suspect abuse.

## Reporting a vulnerability

If you find a security issue in this repo, please **don't** open a public
issue. Email the maintainer privately (see GitHub profile) with details
and a reproducer. Most issues are handled within 48h.

## Audit log

| Date | Audit | Result |
|---|---|---|
| 2026-06-20 | Repo audited at public release | ✅ Clean — no leaks in repo or git history |
