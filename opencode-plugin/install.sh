#!/usr/bin/env bash
# install.sh — install/uninstall the llm-quota-bar OpenCode plugins.
#
# Re-runnable: detects existing symlinks and refuses to double-link.
# Backups opencode.jsonc before patching it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLUGIN_DIR="$REPO_ROOT/opencode-plugin/plugins"
OC_CONFIG_DIR="$HOME/.config/opencode"
OC_CONFIG="$OC_CONFIG_DIR/opencode.jsonc"
OC_PLUGIN_DIR="$OC_CONFIG_DIR/plugins"
BAK="$OC_CONFIG.bak"

SERVER_PLUGIN="$PLUGIN_DIR/llm-statusline.ts"
TUI_PLUGIN="$PLUGIN_DIR/llm-statusline-tui"
CC_STATUSLINE_DIR="$OC_PLUGIN_DIR/cc-statusline"

MARKER="// llm-quota-bar opencode plugins"

usage() {
  cat <<EOF
Usage: $0 [--uninstall]

Default: install (symlinks + patch opencode.jsonc).
--uninstall: remove symlinks and restore opencode.jsonc from backup.
EOF
  exit 1
}

case "${1:-}" in
  "") : ;;
  --uninstall) UNINSTALL=1 ;;
  -h|--help) usage ;;
  *) usage ;;
esac

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

if [[ ! -f "$SERVER_PLUGIN" ]]; then
  echo "ERROR: server plugin not found at $SERVER_PLUGIN" >&2
  exit 1
fi
if [[ ! -d "$TUI_PLUGIN" ]]; then
  echo "ERROR: TUI plugin not found at $TUI_PLUGIN" >&2
  exit 1
fi
if [[ ! -d "$OC_CONFIG_DIR" ]]; then
  echo "ERROR: $OC_CONFIG_DIR not found — is OpenCode installed?" >&2
  exit 1
fi
if [[ ! -d "$CC_STATUSLINE_DIR" ]]; then
  echo "WARN: $CC_STATUSLINE_DIR not found."
  echo "      The TUI plugin needs solid-js/h — symlink from cc-statusline."
  echo "      Either install cc-statusline first, or 'cd $OC_PLUGIN_DIR/llm-statusline-tui && npm install'."
fi

mkdir -p "$OC_PLUGIN_DIR"

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

if [[ "${UNINSTALL:-0}" == "1" ]]; then
  echo "Uninstalling llm-quota-bar opencode plugins…"
  rm -f "$OC_PLUGIN_DIR/llm-statusline.ts"
  rm -rf "$OC_PLUGIN_DIR/llm-statusline-tui"

  if [[ -f "$BAK" ]]; then
    cp "$BAK" "$OC_CONFIG"
    rm -f "$BAK"
    echo "Restored $OC_CONFIG from backup."
  else
    echo "WARN: no backup at $BAK — leaving $OC_CONFIG untouched."
  fi
  echo "Done. Restart OpenCode to apply."
  exit 0
fi

# ---------------------------------------------------------------------------
# Install: symlinks
# ---------------------------------------------------------------------------

echo "Installing llm-quota-bar opencode plugins…"

# Server plugin (single file)
if [[ -L "$OC_PLUGIN_DIR/llm-statusline.ts" ]]; then
  rm -f "$OC_PLUGIN_DIR/llm-statusline.ts"
fi
ln -s "$SERVER_PLUGIN" "$OC_PLUGIN_DIR/llm-statusline.ts"
echo "  ✓ $OC_PLUGIN_DIR/llm-statusline.ts"

# TUI plugin (directory)
if [[ -L "$OC_PLUGIN_DIR/llm-statusline-tui" ]] || [[ -d "$OC_PLUGIN_DIR/llm-statusline-tui" ]]; then
  rm -rf "$OC_PLUGIN_DIR/llm-statusline-tui"
fi
ln -s "$TUI_PLUGIN" "$OC_PLUGIN_DIR/llm-statusline-tui"
echo "  ✓ $OC_PLUGIN_DIR/llm-statusline-tui"

# Share node_modules from cc-statusline so we get solid-js/h
if [[ -d "$CC_STATUSLINE_DIR/node_modules" ]]; then
  ln -sfn "$CC_STATUSLINE_DIR/node_modules" "$TUI_PLUGIN/node_modules"
  echo "  ✓ $TUI_PLUGIN/node_modules (symlinked to cc-statusline)"
else
  echo "  ! Skipped node_modules symlink (cc-statusline not found)."
  echo "    Run: cd $TUI_PLUGIN && npm install"
fi

# Note: the TUI plugin only works once OpenCode implements the TUI plugin
# runtime (tui.js is empty as of 1.17.8). Until then, the server plugin
# (llm-statusline.ts) is what actually delivers the bar via toast.

# ---------------------------------------------------------------------------
# Install: patch opencode.jsonc
# ---------------------------------------------------------------------------

if [[ ! -f "$OC_CONFIG" ]]; then
  echo "ERROR: $OC_CONFIG not found." >&2
  exit 1
fi

if grep -q "$MARKER" "$OC_CONFIG" 2>/dev/null; then
  echo "  ✓ opencode.jsonc already patched (marker found)"
else
  cp "$OC_CONFIG" "$BAK"
  echo "  ✓ Backed up to $BAK"

  # Insert plugin entries inside the "plugin" array. The config can be either
  # JSON or JSONC (with comments and trailing commas). We use a tiny Python
  # pass for robustness.
  python3 - "$OC_CONFIG" <<'PY'
import json, re, sys

path = sys.argv[1]
raw = open(path).read()

# Strip // comments for parsing
stripped = re.sub(r"//[^\n]*", "", raw)

# Try strict JSON first; if that fails, attempt jsonc-style fix
try:
    data = json.loads(stripped)
except json.JSONDecodeError:
    # Remove trailing commas before } or ]
    cleaned = re.sub(r",(\s*[}\]])", r"\1", stripped)
    data = json.loads(cleaned)

plugins = data.setdefault("plugin", [])
new_paths = [
    "./plugins/llm-statusline.ts",
    "./plugins/llm-statusline-tui",
]
for p in new_paths:
    if p not in plugins:
        plugins.append(p)

# We won't try to preserve the original formatting — emit clean JSON
# with a marker comment for the next install/uninstall.
out = json.dumps(data, indent=2)
out = f"{open(path).readline().rstrip()}\n" + out if raw.startswith("//") else out
out += f"\n\n{MARKER}\n"
open(path, "w").write(out)
print("  ✓ Patched opencode.jsonc")
PY
fi

echo ""
echo "Done. Restart OpenCode to load the plugins."
echo ""
echo "What you'll see: after each model response, a 3-line toast appears"
echo "in the top-right corner with model + tokens + cost data."
echo ""
echo "What you won't see (yet): the persistent footer bar and /quota"
echo "command — OpenCode 1.17.8 doesn't ship the TUI plugin runtime."
echo "They will activate automatically once OpenCode implements it."
