// OpenCode plugin: llm-statusline
//
// Multi-provider quota + cost bar for the OpenCode TUI, reusing the same
// Python statusline script that powers fcc-claude:
//   ~/.claude/statusline/session_tokens.py
//
// Architecture
// ------------
// 1. ``session.idle`` fires → query session messages via client.session.messages()
// 2. Extract token totals from AssistantMessage payloads (tokens come from the
//    actual LLM response, not from a server-side event we have to guess about)
// 3. Write JSONL, spawn Python, show quota toast in TUI
//
// Environment
// -----------
// MINIMAX_API_KEY and/or OPENROUTER_API_KEY in shell.

import type { Plugin } from "@opencode-ai/plugin"
import { spawn } from "node:child_process"
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join, sep } from "node:path"

const SCRIPT = join(homedir(), ".claude", "statusline", "session_tokens.py")
const PYTHON = process.env.LLM_STATUSLINE_PYTHON ?? process.env.MINIMAX_STATUSLINE_PYTHON ?? "python3"

const CACHE_DIR = join(homedir(), ".cache", "llm-quota-bar")
const CACHE_FILE = join(CACHE_DIR, "opencode-statusline.txt")

// ---------------------------------------------------------------------------
// Client shape we need (cast from the real OpencodeClient)
// ---------------------------------------------------------------------------
interface Client {
  session: {
    messages(opts: { path: { id: string } }): Promise<{
      data?: Array<{ info: AssistantMsg }>
    }>
  }
  tui: {
    showToast(opts: { body: { message: string; variant: string; title?: string; duration?: number } }): Promise<unknown>
  }
}

interface TokenCache {
  read: number
  write: number
}

interface Tokens {
  input: number
  output: number
  cache: TokenCache
}

interface AssistantMsg {
  role: string
  providerID: string
  modelID: string
  tokens: Tokens
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stripAnsi(s: string): string {
  return s.replace(/\[[0-9;]*m/g, "")
}

function projectHash(dir: string): string {
  return dir.split(sep).join("-")
}

// ---------------------------------------------------------------------------
// Python spawn
// ---------------------------------------------------------------------------

function runPython(projectDir: string, sessionID: string, payload: Record<string, unknown>): Promise<string> {
  return new Promise((resolve) => {
    const proc = spawn(PYTHON, [SCRIPT], {
      env: { ...process.env, CLAUDE_PROJECT_DIR: projectDir, CLAUDE_SESSION_ID: sessionID },
      stdio: ["pipe", "pipe", "pipe"],
    })
    const out: Buffer[] = []
    proc.stdout.on("data", (c: Buffer) => out.push(c))
    proc.stderr.on("data", () => { /* ignore */ })
    proc.on("error", () => resolve(""))
    proc.on("close", (code) => {
      resolve(code === 0 ? Buffer.concat(out).toString().trim() : "")
    })
    try { proc.stdin.write(JSON.stringify(payload)); proc.stdin.end() }
    catch { resolve("") }
  })
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const MiniMaxStatusline: Plugin = async ({ client, directory }) => {
  const cwd = directory ?? process.cwd()

  return {
    event: async ({ event }: { event: { type?: string; properties?: Record<string, unknown> } }) => {
      try {
        if (event?.type !== "session.idle") return
        const sessionID = ((event.properties?.sessionID ?? "") as string)
        if (!sessionID) return

        // Query real messages to get token totals.
        const c = client as unknown as Client
        const res = await c.session.messages({ path: { id: sessionID } })
        const msgs = res?.data ?? []

        let input = 0, output = 0, cacheRead = 0, cacheWrite = 0
        let modelID = "opencode/unknown"

        for (const m of msgs) {
          const info = m.info
          if (!info || (info as AssistantMsg).role !== "assistant") continue
          const t = (info as AssistantMsg).tokens
          input += t.input || 0
          output += t.output || 0
          cacheRead += (t.cache?.read || 0)
          cacheWrite += (t.cache?.write || 0)
          modelID = `${info.providerID || "?"}/${info.modelID || "?"}`
        }

        // Write JSONL (Claude Code compatible).
        const dir = join(homedir(), ".claude", "projects", projectHash(cwd))
        mkdirSync(dir, { recursive: true })
        appendFileSync(join(dir, `${sessionID}.jsonl`), JSON.stringify({
          type: "assistant",
          sessionId: sessionID,
          timestamp: new Date().toISOString(),
          message: {
            role: "assistant",
            model: modelID,
            usage: { input_tokens: input, output_tokens: output, cache_creation_input_tokens: cacheWrite, cache_read_input_tokens: cacheRead },
          },
        }) + "\n", "utf8")

        // Run Python script.
        const bar = await runPython(cwd, sessionID, {
          model: { id: modelID },
          workspace: { current_dir: cwd },
          version: "opencode",
          context_window: { used_percentage: 0 },
          cost: { total_duration_ms: 0 },
        })

        if (bar) {
          try { mkdirSync(CACHE_DIR, { recursive: true }); writeFileSync(CACHE_FILE, bar + "\n", "utf8") } catch { /* noop */ }
        }

        // Python outputs 2-3 lines — show the quota line (tokens + cost).
        const lines = bar ? stripAnsi(bar).split("\n").filter((l: string) => l.trim()) : []
        const line = lines.length >= 2 ? lines[1] : (lines[0] || "no data yet")
        try {
          await c.tui.showToast({
            body: { message: line, variant: "info", title: "📊 Quota", duration: 30000 },
          })
        } catch { /* noop */ }
      } catch {
        // Never crash the TUI.
      }
    },
  }
}
