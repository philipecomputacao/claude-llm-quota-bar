# Changelog

All notable changes to `claude-llm-quota-bar` are documented here. The format is
loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with
versions grouped by date.

## [Unreleased]

### Added
- **Display: 4th line with git info (`🔀 branch • <hash> <commit-title>`).**
  Always rendered. When the resolved cwd is not a git repo, the line shows
  `🔀 [sem git]` (greyed out) so the bar's vertical rhythm stays stable. The
  git lookup runs three short `git` subprocesses (`rev-parse --abbrev-ref HEAD`,
  `rev-parse --short=7 HEAD`, `log -1 --pretty=%s`) bounded by a 1.5 s timeout
  each, with `try/except (OSError, subprocess.TimeoutExpired)` falling back to
  `None` per field. No new dependency — stdlib `subprocess` only. In a non-git
  dir or when git is missing, the line is one grey segment and costs ~5 ms
  (one `.git/` stat).
- **Display: render the active session id on the statusline.** A new line is
  added between the model header and the usage row, formatted as
  `🔖 claude --resume <id>` so the user can copy/paste the command into
  another terminal window to migrate the conversation there. When the
  session id was recovered via the `locate_latest_log` fallback (not the
  exact match from `CLAUDE_SESSION_ID`), a `~` suffix flags the
  imprecision — the id still works for `--resume`, but it may be a
  sibling window's session rather than the one currently rendering. The
  new `ContextInfo` fields (`session_id`, `session_id_inferred`) are
  optional and default to `None` / `False`, so existing callers (tests,
  smoke) are unaffected.
- **`scripts/new_window.sh` — open a new Terminal window that resumes a
  given session.** macOS-only helper that takes a session id (paste it
  from the new statusline bookmark) and an optional cwd, then drives
  Terminal.app via `osascript` to spawn `claude --resume <id>` in a new
  window. Validates the UUID format and the target directory before
  doing anything. Swap `TERMINAL_APP="iTerm"` for iTerm2 users and
  `CLAUDE_CMD=fcc-claude` for the free-claude-code wrapper.
- **Display: detect `fcc-claude` vs `claude` and render the right
  `--resume` command on the bookmark line.** The statusline now inspects
  the `ANTHROPIC_BASE_URL` env var (set to `localhost`/`127.0.0.1` by the
  fcc-server proxy) and renders `fcc-claude --resume <id>` instead of
  `claude --resume <id>` when running under the free-claude-code wrapper.
  Copy-paste from the statusline works without manual editing. Detection
  is centralised in `session_tokens.py:_detect_claude_launcher`; the new
  `ContextInfo.claude_launcher` field defaults to `"claude"`, so existing
  callers are unaffected.
- **Display: 🔀 git line reflects working-tree dirtyness via colour.** The
  branch segment changes colour based on the size of `git diff HEAD`:
  cyan when clean (0 lines), yellow when 50-299 lines changed, red when
  300+ lines changed. Thresholds configurable via `statusline.env.json`
  (`git_dirty_warn_lines`, `git_dirty_alert_lines`, defaults 50/300). A
  `+N/-M` suffix is appended only when the working tree is dirty — clean
  trees stay quiet. Adds one extra `git diff HEAD --numstat` subprocess
  per tick (~10-30 ms in small repos). Uses `git diff HEAD` (not `git diff`
  or `git diff --cached`) so the count covers staged + unstaged against
  HEAD. Untracked files are not counted (out of scope; could be a separate
  "forgot git add" indicator).

### Fixed
- **Display: signal `session_id_inferred` via colour, not suffix.** The
  previous `(inferido)` text marker (commit `7025ab0`) was still
  copy-pasteable as a tail token — a user could paste the whole line
  into a terminal and the shell would ignore the marker, landing in
  whichever session the (inferred) id happened to point at. The
  marker is now rendered only as a colour hint: the `🔖` slot
  keeps the exact `<launcher> --resume <id>` command, in `DIM` when
  the id is inferred and `CYAN` when it is the active window's
  exact session. Copy-paste still works (the colour is a terminal
  attribute, not a character in the stream), but the visual
  contrast signals "double-check before pasting" without polluting
  the selectable text.
- **Session: layered fallback for `CLAUDE_PROJECT_DIR` resolution.** Claude
  Code occasionally drops the `CLAUDE_PROJECT_DIR` env var on some
  refresh ticks — the symptom was a blank statusline slot or a stuck
  `[sem sessão]` placeholder even when the user had a live session. The
  new `_resolve_cwd` helper applies three layers in order:

  1. **Env** — happy path: use the env var when set, and write it to a
     file cache for the next tick.
  2. **Cache** — read `~/.cache/claude-llm-quota-bar/cwd-cache.json`
     (TTL 1h, atomic write via `os.replace`). This covers the typical
     case where Claude Code drops the env var for a few ticks but the
     cwd has not changed.
  3. **lsof** — best-effort: locate the Claude Code process that has
     `~/.claude/settings.json` open, ask lsof for its cwd. macOS-only.
  4. **None** — placeholder with the resolution tag.

  The `_safe_log_path` and `_build_context_info` consumers are
  unchanged — `project_dir` still arrives as a string, just resolved
  through more layers when the env var is missing. The cwd tag is
  captured in the debug dump for post-mortem inspection. Happy-path
  ticks still run in ~90 ms; the cache and lsof layers only activate
  on the failure path.
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
- **Session isolation: always fall back to the most-recent JSONL when the
  session id is missing or unmatched.** The previous `81140be` heuristic
  (`single_jsonl` / `stale_latest` / `ambiguous` gates) was too
  conservative in practice — common multi-window sessions have several
  historical JSONLs in the project dir, so the heuristic was rejecting
  the fallback even for fresh single-window sessions and leaving the
  statusline stuck on `[sem sessão]`. The new `_safe_log_path` always
  returns the most-recent JSONL when the exact match fails, matching the
  pre-`c3cc337` behaviour. The trade-off (a tick on window B with no
  session id could briefly render window A's data) is now visible in the
  statusline via the inline tag — `[sem sessão] · fallback` is only
  shown when there is truly no JSONL to read (`no_jsonls`). The
  `LATEST_LOG_MAX_AGE_SECONDS` constant was removed; the debug dump
  retains the `exact` / `no_jsonls` / `fallback` tag for post-mortem
  inspection.
- **Debug: opt-in diagnostic dump via `CLAUDE_LLM_QUOTA_BAR_DEBUG=1`.**
  When this env var is set, every statusline invocation appends a
  one-line JSON entry to `~/.cache/claude-llm-quota-bar/debug.json` (with
  rotation at 64 KB). Each entry captures the Claude Code contract env
  vars (`CLAUDE_PROJECT_DIR` / `CLAUDE_SESSION_ID` / `CLAUDE_MODEL`),
  the JSONL resolution path taken, and the resolved log path + size.
  Stdin content and any other env are **not** captured — only the public
  contract. Useful for diagnosing "model from another window flickering"
  or "session id not being exported" — set the env var, reproduce the
  issue, then read the debug file.

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