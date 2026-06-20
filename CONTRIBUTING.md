# Contributing

Thanks for your interest in `claude-llm-quota-bar`! 🎉

This document covers how to report bugs, request features, and contribute code
(new providers, quota adapters, docs).

---

## 🐛 Reporting a bug

1. **Search existing issues** first — including closed ones.
2. **Collect the bar output** you're seeing (paste the 3 lines verbatim).
3. **Mention your platform** — Claude Code version / Python version / OS.
4. **Mention which provider** you're testing (MiniMax, OpenRouter, etc.) and
   whether you set the corresponding env var.
5. **Include steps to reproduce** — even rough ones.

If the bug involves the **statusline not appearing at all**, first check the
[TROUBLESHOOTING.md § Troubleshooting](#) in the README.

---

## 💡 Requesting a feature

Open an issue with the `enhancement` label and explain:

- What you're trying to do
- Why the current setup makes it hard
- A sketch of the desired behaviour (even ASCII mockups of the bar are welcome)

---

## 🔌 Adding a new quota adapter

The architecture is intentionally small. A "quota adapter" is one class in
`lib/provider_quota.py` that:

1. Detects whether the adapter applies to the current `model_id` (or
   `provider_id`).
2. Performs the API call (or reuses existing infrastructure).
3. Returns a `QuotaStatus` dataclass with `used_pct`, `status_label`,
   `detail`, `error`, `fetched_at`.

### Skeleton

```python
class NewProviderQuota(QuotaProvider):
    name = "new_provider"
    api_url = "https://api.example.com/v1/usage"
    env_var = "NEW_PROVIDER_API_KEY"
    headers_factory = staticmethod(lambda key: {"Authorization": f"Bearer {key}"})

    def applies_to(self, provider_id: str, model_id: str) -> bool:
        return provider_id == "new_provider"

    def parse(self, raw: dict, now: float) -> QuotaStatus:
        used = raw.get("used", 0)
        limit = raw.get("limit", 1)
        used_pct = round((used / limit) * 100, 1) if limit else 0
        return QuotaStatus(
            used_pct=used_pct,
            status_label=f"{used_pct}% usado ({100 - used_pct:.0f}% livre)",
            detail=f"${used} of ${limit}",
            fetched_at=now,
        )

    def fetch(self) -> dict:
        key = self._read_key()
        if not key:
            raise QuotaError("NEW_PROVIDER_API_KEY not set")
        resp = http_get(self.api_url, headers=self.headers_factory(key))
        return resp.json()
```

Then register it in the `QUOTA_PROVIDERS` registry at the bottom of
`lib/provider_quota.py`. Add a smoke test in the same file's
`if __name__ == "__main__":` block using a `monkeypatch` of `http_get`.

### Contract for adapters

- **Pure**: no global state, no hidden side effects.
- **Tolerant**: missing fields should yield `error=…`, not crash.
- **Cached**: `fetched_at` must be set; the bar suppresses re-renders within
  the FX cache TTL.

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
- `provider` must match an existing `QuotaProvider.name` if you want the
  bar to show quota for this model.

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