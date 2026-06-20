// llm-statusline-tui — Persistent quota bar + /quota toggle command.
//
// Architecture:
// 1. Server plugin (llm-statusline.ts) writes JSONL, spawns Python,
//    saves raw ANSI output to ~/.cache/llm-quota-bar/opencode-statusline.txt
// 2. This TUI plugin polls that cache every 3s and renders the 3-line
//    status bar in the home_bottom slot — just like fcc-claude
// 3. Adds `/quota` slash command to toggle the bar on/off (state stored
//    in ~/.cache/llm-quota-bar/bar-enabled.txt)

import h from "solid-js/h"
import { createSignal, onMount, onCleanup } from "solid-js"
import { readFileSync, writeFileSync, existsSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

const CACHE_DIR = join(homedir(), ".cache", "llm-quota-bar")
const CACHE_FILE = join(CACHE_DIR, "opencode-statusline.txt")
const STATE_FILE = join(CACHE_DIR, "bar-enabled.txt")
const POLL_MS = 3000

const readEnabled = () => {
  try {
    return existsSync(STATE_FILE) ? readFileSync(STATE_FILE, "utf8").trim() !== "0" : true
  } catch {
    return true
  }
}

const writeEnabled = (enabled) => {
  try {
    writeFileSync(STATE_FILE, enabled ? "1" : "0", "utf8")
  } catch { /* ignore */ }
}

const tuiPlugin = async (api) => {
  // State shared across the component
  let enabled = readEnabled()
  const [isEnabled, setIsEnabled] = createSignal(enabled)
  const [line1, setLine1] = createSignal("⏳ llm-quota-bar…")
  const [line2, setLine2] = createSignal("")
  const [line3, setLine3] = createSignal("")

  const toggle = () => {
    enabled = !enabled
    writeEnabled(enabled)
    setIsEnabled(enabled)
    api.tui.showToast({
      body: {
        message: enabled ? "quota bar: ON" : "quota bar: OFF",
        variant: "info",
        title: enabled ? "📊 Quota" : "📊 Quota (off)",
        duration: 4000,
      },
    }).catch(() => {})
  }

  // Register /quota slash command
  api.command.register(() => [
    {
      title: isEnabled() ? "Hide quota bar" : "Show quota bar",
      value: "quota.toggle",
      description: "Toggle the persistent quota status bar in the footer",
      category: "Quota",
      slash: { name: "quota", aliases: ["quota-toggle", "bar"] },
      onSelect: toggle,
    },
  ])

  // Register the home_bottom slot
  api.slots.register(({ Slot }) => {
    const readStatus = () => {
      if (!isEnabled()) return
      try {
        if (!existsSync(CACHE_FILE)) return
        const raw = readFileSync(CACHE_FILE, "utf8").trim()
        if (!raw) return
        const clean = raw.replace(/\x1B\[[0-9;]*m/g, "")
        const lines = clean.split("\n").filter(l => l.trim())
        if (lines.length >= 1) setLine1(lines[0])
        if (lines.length >= 2) setLine2(lines[1])
        if (lines.length >= 3) setLine3(lines[2])
      } catch { /* cache file race */ }
    }

    onMount(() => {
      readStatus()
      const interval = setInterval(readStatus, POLL_MS)
      onCleanup(() => clearInterval(interval))
    })

    return h(Slot, { name: "home_bottom" },
      isEnabled()
        ? h("box", { flexDirection: "column", paddingLeft: 1 },
            h("text", { color: "#888888" }, line1()),
            h("text", { color: "#888888" }, line2()),
            h("text", { color: "#888888" }, line3()),
          )
        : null
    )
  })
}

export const tui = tuiPlugin