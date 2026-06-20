# Contributing

Thanks for your interest in `claude-llm-quota-bar`! 🎉

This document covers how to report bugs, request features, and contribute code
(new providers, quota adapters, docs).

---

## 🐛 Reporting a bug

1. **Search existing issues** first — including closed ones.
2. **Collect the bar output** you're seeing (paste the 3 lines verbatim).
3. **Mention your platform** — Claude Code version / Python version / OS.
4. **Mention which provider** you're testing (Anthropic-native Claude,
   OpenAI direct, Codex ChatGPT, DeepSeek, Mistral, OpenRouter, MiniMax,
   or "other") and whether you set the corresponding env var. If you're
   not routing through a third-party gateway, you can leave this blank —
   the bar works for any provider Claude Code has ever called.
5. **Include steps to reproduce** — even rough ones.

If the bug involves the **statusline not appearing at all**, first check
the [README § Troubleshooting](README.md#troubleshooting) section.

---

## 💡 Requesting a feature

Open an issue with the `enhancement` label and explain:

- What you're trying to do
- Why the current setup makes it hard
- A sketch of the desired behaviour (even ASCII mockups of the bar are welcome)

---

## 🔌 Adding a new quota adapter

The architecture is intentionally small. A "quota adapter" is one class
in `lib/provider_quota.py` that implements the `QuotaProvider` Protocol
defined at `lib/provider_quota.py:67-80`:

```python
class QuotaProvider(Protocol):
    provider_id: str

    def fetch(
        self,
        api_key: str | None = None,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        cache_path: Path | None = None,
        now: float | None = None,
    ) -> QuotaInfo: ...
```

`QuotaInfo` is the dataclass returned by `fetch()` (defined at
`lib/provider_quota.py:49-64`):

```python
@dataclass(frozen=True, slots=True)
class QuotaInfo:
    provider_id: str
    status_label: str          # e.g. "60% livre" / "$8.50 credits" / "free"
    detail: str | None = None  # optional: e.g. "reset 2h48m"
    used_pct: float | None = None  # drives the line colour
    source: str = "static"     # "live" | "cache" | "static" | "error"
    error: str | None = None
    fetched_at: datetime | None = None
```

### Skeleton

```python
class MyProviderQuotaProvider:
    provider_id = "my_provider"

    def fetch(
        self,
        api_key: str | None = None,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        cache_path: Path | None = None,
        now: float | None = None,
    ) -> QuotaInfo:
        # Resolve API key: caller-supplied > env > ~/.fcc/.env
        api_key = api_key or os.environ.get("MY_PROVIDER_API_KEY")
        if not api_key:
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error="MY_PROVIDER_API_KEY not set",
            )

        # Read cache first (shared helper in this file)
        cached = _read_cache(cache_path, cache_ttl_seconds)
        if cached and self.provider_id in cached:
            return cached[self.provider_id]

        # Hit the upstream API
        status, body = _request_json(
            "https://api.my-provider.com/v1/quota",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if status != 200:
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error=f"upstream HTTP {status}: {str(body)[:120]}",
            )

        # Parse and return
        used = body["used"]
        limit = body["limit"] or 1
        used_pct = round((used / limit) * 100, 1)
        return QuotaInfo(
            provider_id=self.provider_id,
            status_label=f"{used_pct:.0f}% usado ({100 - used_pct:.0f}% livre)",
            detail=f"{used:,} of {limit:,}",
            used_pct=used_pct,
            source="live",
            fetched_at=datetime.now(tz=timezone.utc),
        )
```

Then register it in the `QUOTA_PROVIDERS` registry near the bottom of
`lib/provider_quota.py` (search for `QUOTA_PROVIDERS: dict[str, QuotaProvider]`)
and add a smoke test in the same file's
`if __name__ == "__main__":` block (monkeypatch `_request_json` with a
fixture payload — see `MinimaxQuotaProvider` for the canonical pattern).

### Detection chain

The bar picks the adapter from the active model via this priority chain
(in `session_tokens.py::_direct_provider_for_bare_model` and the pricing
lookup):

1. **Gateway prefix** in the model id (`minimax/MiniMax-M3` → `minimax`)
2. **`provider` field** in the resolved pricing entry (`deepseek-v4-pro` → `deepseek`)
3. **Bare-model family heuristic** (e.g. `deepseek-v4-pro` without prefix)
4. **Codex shape** + `~/.codex/auth.json` (valid JWT) → `codex_chatgpt`
5. **Codex shape** + `$OPENAI_API_KEY` (admin) → `openai_dashboard`
6. **No match** → `⏱` segment omitted silently

If your adapter activates from a gateway prefix, that's automatic. If it
activates from a bare model id, add a heuristic in step 3.

### Contract for adapters

- **Pure**: no global state, no hidden side effects.
- **Tolerant**: missing fields should yield `source="error"` /
  `status_label="error"` with an `error=` description — never raise.
- **Cached**: `fetched_at` must be set on success so the next render can
  skip re-fetching within the cache TTL.
- **Provider id is stable contract**: `provider_id` is the cache key in
  `~/.cache/claude-llm-quota-bar/provider-quota.json` and the registry
  key in `QUOTA_PROVIDERS`. Renaming it is a hard runtime break — don't.

---

## 🤖 Adding a new pricing entry

Edit `pricing.json` (402 entries today) following the existing shape:

```json
"new-provider/new-model": {
  "input": 3.0,
  "output": 15.0,
  "context_window": 200000,
  "modality": "text",
  "provider": "new_provider"
}
```

- `input` / `output` are **USD per 1M tokens** (industry standard).
- `context_window` is in tokens.
- `modality` ∈ `text` / `vision` / `audio` / `embedding`.
- `provider` must match an existing `QuotaProvider.provider_id` if you
  want the bar to show quota for this model.

You can also re-run `scripts/build_pricing.py` to regenerate from the
upstream tables (it has a `--diff` mode that only updates entries whose
price actually changed).

---

## 🧹 Style

- **Python**: stdlib only — no `requests`, no `pydantic`. Match the style
  of the surrounding file (`lib/provider_quota.py`).
- **Shell**: `bash` with `set -euo pipefail`. Idempotent (re-runnable).
- **Commits**: Conventional Commits-lite in PT-BR, e.g.
  `feat(quota): adiciona adapter para NewProvider`,
  `fix(statusline): corrige cor quando quota > 100%`,
  `docs: revisa SECURITY.md`. End with
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## 🔒 Security disclosures

**Do not** open a public issue for security vulnerabilities. Email the
maintainer privately (see GitHub profile). See [SECURITY.md](SECURITY.md)
for the full policy.