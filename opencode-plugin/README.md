# opencode-plugin — Multi-provider quota bar for OpenCode

> Reuses the [`session_tokens.py`](../session_tokens.py) statusline from the
> same repo to deliver a live token + cost + burn-rate + **provider quota**
> bar inside [OpenCode][oc]. Same data source as fcc-claude, different
> delivery channel.

[oc]: https://opencode.ai

## Status (2026-06, OpenCode 1.17.8)

| Feature | Works? |
|---|---|
| Server plugin: 3-line toast on every `session.idle` | ✅ Yes |
| Persistent bar in `home_bottom` slot | ⏳ Waiting for TUI plugin runtime |
| `/quota` slash command | ⏳ Same |

The OpenCode SDK ships **types** for `api.slots`, `api.command`, and
`api.ui` in `tui.d.ts`, but `tui.js` is empty (`export {};`). The
persistent bar and `/quota` command will activate **without code changes**
once OpenCode ships the TUI plugin runtime.

The server plugin uses the **fully-implemented** `OpencodeClient` SDK
(`client.tui.showToast`), which is what you see today.

## What you get

When you send a message in OpenCode, a toast appears (30s) with 3 lines:

```
📊 Quota
[MiniMax-M3·minimax] • 📁 ~/Projetos/foo • 📟 vopencode
⬆1.0M ⬇48k ↻R2.8M • ⏱ 40% usado (60% livre) (reset 2h48m) • 🧠 12% usado (88% livre)
🇧🇷 R$1.61 🇺🇸 $0.312 • ⌛ 25m • ⚡ 42951t/m
```

Same 3-line bar fcc-claude shows, just delivered as a toast instead of a
persistent footer.

## How it works

```
┌────────────────────┐  session.idle   ┌────────────────────┐
│  OpenCode TUI      │ ──────────────► │  llm-statusline.ts │
└────────────────────┘                 │  (server plugin)   │
        ▲                              └──────────┬──────────┘
        │ shows 3-line toast                       │ spawns
        │ (client.tui.showToast)                   ▼
        │                                ┌────────────────────┐
        │                                │ session_tokens.py  │
        │                                │ (parent repo)      │
        │                                └──────────┬──────────┘
        │                                           │ writes
        │                                           ▼
        │                                ~/.cache/llm-quota-bar/
        │                                opencode-statusline.txt
        │                                           │
        │                                polled every 3s by TUI plugin
        │                                (renders 3-line bar in home_bottom
        │                                 when TUI plugin runtime ships)
        │                                           ▼
        │                                ┌────────────────────┐
        └────────────────────────────────│ llm-statusline-tui │
                                         │ (TUI plugin)       │
                                         └────────────────────┘
```

**Two plugins, two delivery channels:**

1. **Server plugin** (`plugins/llm-statusline.ts`) — listens to `session.idle`,
   queries real token totals via `client.session.messages()` (not from event
   payloads which lack tokens), spawns `session_tokens.py`, shows the
   3-line toast via `client.tui.showToast`. **Active today.**

2. **TUI plugin** (`plugins/llm-statusline-tui/index.js`) — registers
   `home_bottom` slot, polls the cache file every 3s, renders the bar with
   `@opentui/solid`. Also registers `/quota` slash command. **Inactive until
   OpenCode ships TUI plugin runtime.**

The two share state via the cache file (`~/.cache/llm-quota-bar/opencode-statusline.txt`),
so no in-memory coupling — you can run either independently.

## Slash command: `/quota`

> ⏳ **Inactive in OpenCode 1.17.8.** Will activate with the TUI runtime.

When active, `/quota` (aliases: `/quota-toggle`, `/bar`) toggles the
persistent bar on/off. State persists in
`~/.cache/llm-quota-bar/bar-enabled.txt` (default: ON).

Today the toast auto-dismisses after 30s. A new toast fires on the next
`session.idle` (each message after the model responds).

## Install

From the repo root:

```bash
./opencode-plugin/install.sh
```

The script is idempotent:

1. Symlinks `plugins/llm-statusline.ts` → `~/.config/opencode/plugins/`
2. Symlinks `plugins/llm-statusline-tui/` → `~/.config/opencode/plugins/`
3. Symlinks `node_modules` from `~/.config/opencode/plugins/cc-statusline/`
   (shared `solid-js` install) — the TUI plugin needs `solid-js/h` to load
4. Patches `~/.config/opencode/opencode.jsonc` to register both plugins
5. Backs up `opencode.jsonc` to `opencode.jsonc.bak` before patching

Re-run safely. It overwrites symlinks and skips the `opencode.jsonc` patch
if the marker comment `// llm-quota-bar opencode plugins` is already present.

## Uninstall

```bash
./opencode-plugin/install.sh --uninstall
```

Removes the symlinks and restores `opencode.jsonc` from
`opencode.jsonc.bak`. If the backup is missing, the script warns and
leaves `opencode.jsonc` untouched (manual cleanup required).

## Requirements

- OpenCode ≥ 1.17.0 (server plugin uses `client.session.messages()` API)
- Python 3.10+ (for `session_tokens.py`)
- `solid-js` available via `cc-statusline` plugin's `node_modules` for the
  TUI plugin to load — only needed once the TUI runtime ships

## API keys for live quota

The `⏱` segment only renders when the matching API key is set. Add to
`~/.zshrc` or `~/.bashrc`:

```bash
export MINIMAX_API_KEY=sk-cp-...           # MiniMax Token Plan
export OPENROUTER_API_KEY=sk-or-...         # OpenRouter credits
export DEEPSEEK_API_KEY=sk-...              # DeepSeek balance
export MISTRAL_API_KEY=ms-...               # Mistral usage
export OPENAI_API_KEY=sk-admin-...          # OpenAI credit grants (admin key)
```

Or in `~/.fcc/.env` — `session_tokens.py` reads both, env vars win.

**No keys live in this repo** — they're only referenced by name in
`session_tokens.py` and `lib/provider_quota.py`. See [Security](#security)
below.

## Security

The plugin and its parent script follow the central's secret-handling
rules:

1. **API keys live in your shell env or `~/.fcc/.env`** — never committed
2. **All caches go to `~/.cache/llm-quota-bar/`** — gitignored by the
   central's standard `.gitignore` (`*.cache/`, `*.env*`)
3. **The cache file holds only public output** (3 status lines, in
   `provider-quota.json` only `used_pct` + `status_label` + reset time —
   no tokens, no keys, no request bodies)
4. **`opencode debug config` exposes resolved keys** only because
   `{env:MINIMAX_API_KEY}` is interpolated at runtime — keys themselves
   stay in your shell, not in the committed config file

If you accidentally leak a key, the central recommends
`ferramentas/_docs/secrets.md` (TODO link once that exists).

## Files

```
opencode-plugin/
├── README.md                         ← this file
├── install.sh                        ← installer (idempotent)
└── plugins/
    ├── llm-statusline.ts             ← server plugin (active)
    └── llm-statusline-tui/           ← TUI plugin (waiting for runtime)
        ├── package.json
        └── index.js
```

## License

Apache 2.0 — same as the parent project.
