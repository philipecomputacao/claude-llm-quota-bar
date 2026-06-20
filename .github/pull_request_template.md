## What

<!-- One or two sentences. What does this PR do? -->

## Why

<!-- What's the motivation? Link the issue if relevant. -->

## How

<!-- One paragraph. The interesting bit. -->

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] I did **not** commit any real API keys, session tokens, or credentials
  (only env var **names** are OK; values are not)
- [ ] I added or updated tests (if applicable — quota adapters have
  smoke tests in the same file)
- [ ] I ran `python3 -m py_compile session_tokens.py lib/*.py`
  (no errors)
- [ ] For new providers: I updated `pricing.json` with at least the
  entry I tested

## Security

- [ ] I have **not** introduced any new env var that holds secrets
  (only optional config knobs)
- [ ] I have **not** logged any token, key, or session body
- [ ] I have updated [SECURITY.md](../SECURITY.md) if the change affects
  what gets cached at runtime

## Linked issues

<!-- Closes #123, fixes #456 -->