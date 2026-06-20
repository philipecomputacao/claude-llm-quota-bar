---
name: 💡 Feature request
about: Suggest a new provider, quota adapter, or statusline segment
title: '[FEAT] '
labels: enhancement
assignees: ''
---

## Problem

<!-- What are you trying to do that the current setup makes hard? -->

## Proposed solution

<!-- Sketch the desired behaviour. ASCII mockups of the bar are welcome. -->

```
⬆ ⬇ ↻R • ⏱ 42% usado (58% livre) (reset 1h) • 🧠 12% usado (88% livre)
🇧🇷 R$ 1.61 🇺🇸 $ 0.31 • ⌛ 25m • ⚡ 42951t/m
```

<!-- Modify above to show what the new line would look like. -->

## Alternatives considered

<!-- Other approaches you weighed and why you didn't pick them. -->

## Provider / API specifics (if adding a new adapter)

- **Provider name**:
- **Auth**: (env var name, format)
- **Quota endpoint**:
- **Response shape** (paste a redacted example, **no real keys**):

```json
{
  "used": 0,
  "limit": 0,
  "reset_at": "..."
}
```

## Willing to PR?

<!-- Yes / No / Maybe with help. If yes, see CONTRIBUTING.md § "Adding a new quota adapter" for the skeleton matching the real QuotaProvider Protocol. -->