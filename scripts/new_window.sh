#!/usr/bin/env bash
# new_window.sh — Open a new Terminal/iTerm window that resumes a given session.
#
# Usage:
#   ./scripts/new_window.sh <session_id> [cwd]
#
# Environment variables (override defaults):
#   CLAUDE_CMD    Which Claude launcher to invoke. Default: "claude".
#                 Set to "fcc-claude" if you use the free-claude-code wrapper.
#   TERMINAL_APP  Which macOS terminal to drive. Default: "Terminal".
#                 Set to "iTerm" if you use iTerm2.
#
# Examples:
#   ./scripts/new_window.sh fa26c77b-3790-412c-9c59-7e267c257b9f
#       # opens Terminal.app in $HOME, runs `claude --resume <id>`
#
#   CLAUDE_CMD=fcc-claude \
#   ./scripts/new_window.sh fa26c77b-...  ~/Projetos/projetos/claude-llm-quota-bar
#       # opens Terminal.app in the project dir, runs `fcc-claude --resume <id>`
#
# Arguments:
#   <session_id>  The Claude Code session UUID (36 chars) to resume. Copy it
#                 from the statusline (the line starting with the bookmark
#                 emoji: `claude --resume <id>`).
#   [cwd]         Optional. The directory to cd into before launching Claude
#                 Code. Defaults to $HOME when omitted. The original session's
#                 cwd is no longer accessible from the active window, so we
#                 ask for it explicitly — picking the wrong cwd would make
#                 --resume land in the wrong project context.
#
# macOS only (uses osascript to drive Terminal.app). Tested on Darwin 25.2.0.
#
# Setup (one time):
#   chmod +x scripts/new_window.sh
#
# Step by step:
#   1. In any Claude Code window, look at the statusline (the line marked
#      with the bookmark emoji 🔖) and copy the session id — it is the
#      36-character UUID right after `claude --resume `.
#   2. Open a fresh Terminal tab/window.
#   3. Run:
#        cd ~/Projetos/projetos/claude-llm-quota-bar
#        ./scripts/new_window.sh <session_id> [desired_cwd]
#      For example:
#        ./scripts/new_window.sh fa26c77b-3790-412c-9c59-7e267c257b9f ~/Projetos/projetos/claude-llm-quota-bar
#   4. A new Terminal window opens, cd's to the chosen directory, and runs
#      `claude --resume <id>`. The conversation history loads and the
#      statusline reappears with the same model/tokens.
#
# Gotchas:
#   - The script MUST be run from a terminal that has access to the
#     `osascript` binary (built-in on macOS).
#   - The chosen cwd must be the same project the original session was
#     running in, otherwise --resume will load the conversation but the
#     file paths referenced inside will not resolve correctly.
#   - If Terminal.app is not your default terminal, edit the osascript
#     block below to target iTerm2 (`on run argv ... tell application
#     "iTerm" to create window with default profile ...`).
#
# Variables in the config block:
#   TERMINAL_APP  Which macOS terminal to drive. Default: "Terminal".
#                  Swap to "iTerm" if you use iTerm2.
#   CLAUDE_CMD    Which Claude Code launcher to invoke. Default: "claude".
#                  Set to "fcc-claude" if you use the free-claude-code wrapper
#                  (the one installed at ~/.local/bin/fcc-claude). Both
#                  accept the same --resume <id> flag.

set -euo pipefail

# --- Configuration ---
TERMINAL_APP="${TERMINAL_APP:-Terminal}"
CLAUDE_CMD="${CLAUDE_CMD:-claude}"

# --- Input validation ---
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <session_id> [cwd]" >&2
  echo "" >&2
  echo "  <session_id>  36-char UUID (copy from the statusline bookmark)" >&2
  echo "  [cwd]         Directory to cd into (default: \$HOME)" >&2
  exit 64  # EX_USAGE
fi

SESSION_ID="$1"
TARGET_CWD="${2:-$HOME}"

# Basic sanity check on the session id format (UUID v4-ish).
if [[ ! "$SESSION_ID" =~ ^[a-f0-9-]{36}$ ]]; then
  echo "Error: session_id '$SESSION_ID' does not look like a 36-char UUID." >&2
  echo "Copy it from the statusline (the line starting with the bookmark emoji)." >&2
  exit 65  # EX_DATAERR
fi

if [[ ! -d "$TARGET_CWD" ]]; then
  echo "Error: cwd '$TARGET_CWD' does not exist or is not a directory." >&2
  exit 66  # EX_NOINPUT
fi

# --- Drive the terminal app ---
# We escape the cwd and session id for safe embedding inside the AppleScript
# string. The `quoted form of` construct handles quoting/spaces correctly.
ESCAPED_CWD=$(printf '%s' "$TARGET_CWD" | sed "s/'/'\\\\''/g")
ESCAPED_ID=$(printf '%s' "$SESSION_ID" | sed "s/'/'\\\\''/g")
ESCAPED_CMD=$(printf '%s' "$CLAUDE_CMD" | sed "s/'/'\\\\''/g")

osascript <<EOF
tell application "$TERMINAL_APP"
  activate
  do script "cd '$ESCAPED_CWD' && $ESCAPED_CMD --resume '$ESCAPED_ID'"
end tell
EOF
