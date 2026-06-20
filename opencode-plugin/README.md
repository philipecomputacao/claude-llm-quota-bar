# opencode-plugin — Multi-provider quota bar for OpenCode

> A persistent 3-line status bar for [OpenCode][oc] that reuses the
> [`session_tokens.py`](../session_tokens.py) statusline from the same repo.
> Live token + cost + burn-rate + **provider quota** bar with colour-coded
> alerts, identical to what the fcc-claude fork renders.

[oc]: https://opencode.ai

## What you get

```
[MiniMax-M3·minimax] • 📁 ~/Projetos/foo • 📟 vopencode
⬆1.0M ⬇48k ↻R2.8M • ⏱ 40% usado (60% livre) (reset 2h48m) • 🧠 12% usado (88% livre)
🇧🇷 R$1.61 🇺🇸 $0.312 • ⌛ 25m • ⚡ 42951t/m
```

Three lines, persistent in the OpenCode TUI footer, polling every 3s.

## How it works

```
┌────────────────────┐  session.idle   ┌────────────────────┐
│  OpenCode TUI      │ ──────────────► │  llm-statusline.ts │
└────────────────────┘                 │  (server plugin)   │
        ▲                              └──────────┬──────────┘
        │ renders 3 lines                         │
        │ home_bottom slot                        │ spawns
        │                                         ▼
        │                                ┌────────────────────┐
        │                                │ session_tokens.py  │
        │                                │ (this repo)        │
        │                                └──────────┬──────────┘
        │                                           │ writes
        │                                           ▼
        │                                ~/.cache/llm-quota-bar/
        │                                opencode-statusline.txt
        │                                           │
        │                                polled every 3s by
        │                                           ▼
        │                                ┌────────────────────┐
        └────────────────────────────────│  llm-statusline-   │
                                         │  tui/index.js      │
                                         │  (TUI plugin)      │
                                         └────────────────────┘
```

**Two plugins collaborate:**

1. **Server plugin** (`plugins/llm-statusline.ts`) — listens to `session.idle`
   events, queries real token totals from `client.session.messages()` (so we
   don't depend on event payloads), spawns `session_tokens.py`, and writes
   the bar to `~/.cache/llm-quota-bar/opencode-statusline.txt`.

2. **TUI plugin** (`plugins/llm-statusline-tui/index.js`) — registers a slot
   in `home_bottom`, polls the cache file every 3s, and renders the bar with
   `@opentui/solid` (the same renderer OpenCode uses internally).

The two plugins share state via the cache file — no in-memory coupling needed.

## Slash command: `/quota`

```
> /quota
```

Toggles the persistent bar on/off. Aliases: `/quota-toggle`, `/bar`. The
state is persisted in `~/.cache/llm-quota-bar/bar-enabled.txt` (default: ON).

When the bar is off, a small toast confirms: `quota bar: OFF` / `quota bar: ON`.

## Install

The plugin is **not** self-installing. From the repo root:

```bash
./opencode-plugin/install.sh
```

This script:

1. Symlinks `plugins/llm-statusline.ts` → `~/.config/opencode/plugins/`
2. Symlinks `plugins/llm-statusline-tui/` → `~/.config/opencode/plugins/`
3. Symlinks `node_modules` from the `cc-statusline` plugin (shared
   `solid-js` install) so the TUI plugin can resolve `solid-js/h`
4. Patches `~/.config/opencode/opencode.jsonc` to register both plugins
5. Backs up `opencode.jsonc` to `opencode.jsonc.bak` before patching

Re-run safely — it overwrites symlinks and refuses to patch `opencode.jsonc`
without the marker comment `// llm-quota-bar opencode plugins`.

## Uninstall

```bash
./opencode-plugin/install.sh --uninstall
```

Removes the symlinks and the `plugin` entries from `opencode.jsonc` (restored
from `opencode.jsonc.bak`).

## Requirements

- OpenCode ≥ 1.17.0 (TUI slot API)
- Python 3.10+ (for `session_tokens.py`)
- `solid-js` available via the `cc-statusline` plugin's `node_modules`
  (auto-linked by `install.sh`)

## API keys for live quota

The `⏱` segment only renders if the matching API key is set. Add to
`~/.zshrc` or `~/.bashrc`:

```bash
export MINIMAX_API_KEY=sk-cp-...           # MiniMax Token Plan
export OPENROUTER_API_KEY=sk-or-...         # OpenRouter credits
export DEEPSEEK_API_KEY=sk-...              # DeepSeek balance
export MISTRAL_API_KEY=ms-...               # Mistral usage
export OPENAI_API_KEY=sk-admin-...          # OpenAI credit grants (admin key)
```

Or in `~/.fcc/.env` — the script reads both, env vars win.

## Files

```
opencode-plugin/
├── README.md                         ← this file
├── install.sh                        ← installer
└── plugins/
    ├── llm-statusline.ts             ← server plugin (events, JSONL, Python spawn)
    └── llm-statusline-tui/           ← TUI plugin (persistent bar + /quota command)
        ├── package.json
        └── index.js
```

## License

Apache 2.0 — same as the parent project.
