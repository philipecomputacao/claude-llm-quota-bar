#!/usr/bin/env python3
"""Claude Code statusline entry point.

Reads the Claude Code session JSONL, aggregates token usage, computes cost
using a price table, and prints a one-line status to stdout. Designed to be
fast (<50ms) because Claude Code refreshes it periodically.

Environment variables (set by Claude Code):
- ``CLAUDE_PROJECT_DIR``: absolute path of the cwd of the Claude Code session.
- ``CLAUDE_SESSION_ID``: unique session id used to locate the JSONL file.
- ``CLAUDE_MODEL`` (optional): the active model id.

Stdin (Claude Code >=2.1): JSON object with current model + cost context.
This script does not depend on stdin to work; it is treated as a hint.

Configuration: see ``pricing.json`` next to this file and
``statusline.env.json`` (optional) for display toggles.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from lib.display import ContextInfo, DisplayOptions, render  # noqa: E402
from lib.fx import DEFAULT_TTL_SECONDS, resolve_rate  # noqa: E402
from lib.git import resolve_git  # noqa: E402
from lib.parser import (  # noqa: E402
    TokenTotals,
    _provider_from_model,
    _strip_gateway_prefix,
    locate_session_log,
    parse_first_response_model,
    project_dir_to_hash,
)
from lib.provider_quota import fetch_quota  # noqa: E402
from lib.pricing import (  # noqa: E402
    CostBreakdown,
    ModelPrice,
    compute_cost,
    load_pricing_table,
)

DEFAULT_CLAUDE_DIR = Path.home() / ".claude"
PLACEHOLDER = "[statusline: inicializando]"
NO_SESSION_PLACEHOLDER = "[sem sessão]"

# When set, the statusline writes a diagnostic dump to
# ``~/.cache/claude-llm-quota-bar/debug.json`` on every invocation. Useful
# for investigating "model from another window is flickering" — the dump
# captures the env vars Claude Code exported, the JSONL resolution result,
# and the resolved totals. Disabled by default.
DEBUG_ENV = "CLAUDE_LLM_QUOTA_BAR_DEBUG"
DEBUG_CACHE_FILENAME = "debug.json"
DEBUG_MAX_BYTES = 64 * 1024  # rotate if larger than this

# Cache of the last ``CLAUDE_PROJECT_DIR`` we successfully resolved. Each
# statusline invocation is a brand-new process (Claude Code re-spawns the
# command on every refresh tick), so an in-memory cache is useless across
# ticks. We persist the cwd to disk so the NEXT tick can pick it up when
# Claude Code forgets to export ``CLAUDE_PROJECT_DIR`` — a known flaky
# behaviour that used to leave the user stuck on the ``[sem sessão]``
# placeholder. 1 hour TTL is generous: Claude Code usually drops the env
# var for seconds at a time, never hours.
CWD_CACHE_FILENAME = "cwd-cache.json"
CWD_CACHE_MAX_AGE_SECONDS = 3600  # 1 hour
# Tag surfaced in the debug dump / inline placeholder so the user can tell
# which layer resolved the cwd (env, cache, lsof, or none).
CWD_TAG_ENV = "env"
CWD_TAG_CACHE = "cache"
CWD_TAG_LSOF = "lsof"
CWD_TAG_NONE = "none"


def _safe_file_size(path: Path) -> int:
    """Return ``path.stat().st_size``, or 0 on any OSError.

    Defensive wrapper — a concurrent delete between ``exists()`` and
    ``stat()`` is possible but rare. Never raises.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0

# Note: previous revisions had a ``LATEST_LOG_MAX_AGE_SECONDS`` constant and
# an "ambiguous" branch that refused the fallback when the project dir
# contained multiple JSONLs. That branch ended up rejecting the fallback
# for sessions with accumulated history (multiple historical JSONLs in
# the same project_dir) and stuck the user on the [sem sessão] placeholder
# even in the obvious "single window" case. Reverted to the original
# ``locate_latest_log`` behaviour below — see ``_safe_log_path`` docstring.


def _load_display_options(config_path: Path) -> DisplayOptions:
    """Load display toggles from ``statusline.env.json`` if present.

    Values from JSON are coerced to the types declared on :class:`DisplayOptions`
    so a user-typed string (``"50"`` instead of ``50``) does not cause a
    ``TypeError`` at comparison time deep inside the render pipeline.
    """
    if not config_path.exists():
        return DisplayOptions()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DisplayOptions()
    allowed = {f for f in DisplayOptions.__dataclass_fields__}
    kwargs: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in allowed:
            continue
        field_type = DisplayOptions.__dataclass_fields__[k].type
        kwargs[k] = _coerce_option(v, field_type)
    return DisplayOptions(**kwargs)


def _coerce_option(value: Any, target_type: Any) -> Any:
    """Coerce a JSON value to the target type declared in :class:`DisplayOptions`.

    Handles the three type families used by the options dataclass: ``bool``
    (``"true"``/``"false"`` → ``True``/``False``), ``int``, and ``float``.
    Strings for ``ColorMode`` and invalid values are passed through unscathed
    so downstream code can apply the default (the dataclass field default
    handles missing keys; this function handles wrong-type values for keys
    that *are* present).
    """
    if target_type is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)
    if target_type is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if target_type is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    # ``ColorMode`` (Literal["auto", "always", "never"]) stays as a string;
    # unrecognised types pass through unchanged so the dataclass default
    # applies if the value is invalid.
    return value


def _read_stdin() -> dict[str, Any]:
    """Read Claude Code's stdin JSON hint, returning ``{}`` on failure."""
    try:
        payload = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def _debug_dump(payload: dict[str, Any], *, force: bool = False) -> None:
    """Append a single-line JSON entry to the debug cache file.

    By default, only writes when :data:`DEBUG_ENV` is set (opt-in). When
    ``force=True``, writes regardless — used to capture the failure path
    (placeholder shown) even when the user has not opted in, so that the
    bug can be diagnosed from a single ``cat`` of the file without having
    to re-export the env var.

    Best-effort: any failure (missing cache dir, permission error) is
    swallowed silently so the debug mode never breaks the statusline. The
    file is rotated when it exceeds :data:`DEBUG_MAX_BYTES`. Captures only
    public signal — env vars, JSONL resolution result, totals — never stdin
    contents or anything that could contain user data.
    """
    if not force and not os.environ.get(DEBUG_ENV):
        return
    try:
        cache_dir = DEFAULT_CLAUDE_DIR.parent / ".cache" / "claude-llm-quota-bar"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / DEBUG_CACHE_FILENAME
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        # Rotate if too large.
        try:
            if path.exists() and path.stat().st_size > DEBUG_MAX_BYTES:
                path.write_text(line, encoding="utf-8")
                return
        except OSError:
            pass
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return


def _debug_env_summary() -> dict[str, str | None]:
    """Return only the Claude Code contract env vars (no other env, no secrets)."""
    return {
        "CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR"),
        "CLAUDE_SESSION_ID": os.environ.get("CLAUDE_SESSION_ID"),
        "CLAUDE_MODEL": os.environ.get("CLAUDE_MODEL"),
    }


def _list_project_jsonls(claude_dir: Path, project_dir: str) -> list[Path]:
    """List JSONLs in the project directory, sorted by mtime ascending."""
    if not project_dir:
        return []
    project_hash = project_dir_to_hash(project_dir)
    project_path = claude_dir / "projects" / project_hash
    if not project_path.exists():
        return []
    return sorted(project_path.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def _safe_log_path(
    claude_dir: Path,
    project_dir: str,
    session_id: str,
) -> tuple[Path | None, str | None, str, bool]:
    """Locate the JSONL path for the given session.

    Resolution order:

    1. **Exact match** — ``locate_session_log(claude_dir, project_dir,
       session_id)``. Returns the path if found.
    2. **Latest JSONL fallback** — when no exact match is found OR the
       session id is empty (Claude Code tick that failed to export
       ``CLAUDE_SESSION_ID``), use ``locate_latest_log`` to pick the
       most-recent JSONL in the project directory. This is the original
       pre-c3cc337 behaviour; see the commit message for the trade-off
       discussion.
    3. Otherwise (no JSONLs in the project dir) return
       ``(None, None, "no_jsonls", False)`` and let the caller render
       :data:`NO_SESSION_PLACEHOLDER`.

    Returns ``(path, resolved_session_id, resolution_tag, inferred)`` where
    ``resolved_session_id`` is the stem of the JSONL we ended up reading —
    either the one Claude Code exported (when exact) or the one we picked
    from the latest JSONL (when fallback). The 4th flag ``inferred`` is True
    when the id came from the fallback path (the user should treat it as a
    hint, not as the window's exact id).
    """
    if session_id:
        path = locate_session_log(claude_dir, project_dir, session_id)
        if path is not None:
            return path, session_id, "exact", False
    # No session id (or no exact match). Fall back to the most-recent
    # JSONL in the project directory. This is the original pre-c3cc337
    # behaviour: it may briefly surface a sibling window's data when two
    # Claude Code windows share the same cwd AND a tick on one of them
    # loses its session id, but in practice the tick recovers on the next
    # refresh (5 s later) and the flicker is rare. The cost of being
    # conservative (refusing the fallback) was that sessions with
    # accumulated history in the project dir were stuck on the
    # ``[sem sessão]`` placeholder indefinitely — the user has multiple
    # historical JSONLs in their project dir, and any new window opened
    # in that dir ended up on the placeholder path because the latest
    # JSONL was ambiguous with the historical ones.
    #
    # The cross-window flicker is still observable via the debug dump
    # (set ``CLAUDE_LLM_QUOTA_BAR_DEBUG=1``) if it becomes a problem
    # again.
    jsonls = _list_project_jsonls(claude_dir, project_dir)
    if not jsonls:
        return None, None, "no_jsonls", False
    latest = jsonls[-1]
    return latest, latest.stem, "fallback", True


# Statusline parses the JSONL on every refresh. To avoid re-reading a
# multi-MB file every 5 s (which can briefly blank the TUI), we memoize
# the result keyed on (path, mtime, size) for a short window. Claude Code
# only writes appendFileSync, so the file is append-only — the mtime/size
# tuple uniquely identifies the content of the tail we already parsed.
_AGGREGATE_CACHE: dict[tuple[str, int, int], tuple[float, "TokenTotals"]] = {}
_AGGREGATE_CACHE_TTL_SECONDS = 2.0


def _aggregate_cached(jsonl_path: Path, session_id: str | None) -> "TokenTotals":
    """Return aggregate_session(jsonl_path, session_id), cached for ~2 s.

    Cache key is (path, mtime_ns, size). When Claude Code appends a new
    assistant entry, the size grows and we re-parse only the tail. The
    2 s window aligns with the Claude Code statusline refresh interval
    (5 s) so consecutive refreshes reuse the parsed result.
    """
    from lib.parser import aggregate_session  # local import to avoid cycle

    try:
        st = jsonl_path.stat()
    except OSError:
        return TokenTotals()
    key = (str(jsonl_path), st.st_mtime_ns, st.st_size)
    now = time.monotonic()
    cached = _AGGREGATE_CACHE.get(key)
    if cached is not None:
        ts, totals = cached
        if now - ts < _AGGREGATE_CACHE_TTL_SECONDS:
            return totals
        # Stale entry — drop it and refetch.
        _AGGREGATE_CACHE.pop(key, None)
    # Opportunistic cache prune so the dict does not grow unbounded across
    # very long sessions that touch many JSONL files.
    for k, (ts, _) in list(_AGGREGATE_CACHE.items()):
        if now - ts > _AGGREGATE_CACHE_TTL_SECONDS * 4:
            _AGGREGATE_CACHE.pop(k, None)
    totals = aggregate_session(jsonl_path, session_id or "")
    _AGGREGATE_CACHE[key] = (now, totals)
    return totals


def _detect_claude_launcher() -> str:
    """Return ``"fcc-claude"`` if running under the free-claude-code wrapper,
    otherwise ``"claude"``.

    The detection is based on the ``ANTHROPIC_BASE_URL`` env var that
    fcc-claude sets to the local ``fcc-server`` proxy URL. When the URL
    points to localhost/127.0.0.1 we are almost certainly behind the
    fcc-claude wrapper. Anything else (unset, or pointing at the official
    Anthropic API) means a vanilla ``claude`` invocation.

    Reference: fcc-claude source at
    ``~/.local/share/uv/tools/free-claude-code/lib/.../cli/launchers/claude.py``
    sets ``env["ANTHROPIC_BASE_URL"] = proxy_root_url`` where
    ``proxy_root_url`` resolves to ``http://localhost:<port>``.
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip().lower()
    if not base_url:
        return "claude"
    if "localhost" in base_url or "127.0.0.1" in base_url or "::1" in base_url:
        return "fcc-claude"
    return "claude"


def _stdin_cwd(stdin_hint: dict[str, Any], fallback: str | None) -> str | None:
    """Extract the working directory from Claude Code's stdin payload.

    Priority: ``workspace.current_dir`` → ``workspace.project_dir`` →
    ``cwd`` → ``fallback``. Returns ``None`` when every layer is empty.

    This is a tiny shared helper so that both ``_build_context_info`` and
    ``main()`` (for ``resolve_git``) use the same CWD — without it, the
    git line shows ``[sem git]`` when ``CLAUDE_PROJECT_DIR`` is unset but
    the stdin payload carries the cwd (the statusline renders the folder
    correctly but ``resolve_git`` sees an empty string).
    """
    cwd: str | None = None
    workspace = stdin_hint.get("workspace") if isinstance(stdin_hint, dict) else None
    if isinstance(workspace, dict):
        cwd = workspace.get("current_dir") or workspace.get("project_dir")
    if not cwd and isinstance(stdin_hint, dict):
        cwd = stdin_hint.get("cwd")
    return cwd or fallback


def _build_context_info(
    stdin_hint: dict[str, Any],
    project_dir_fallback: str,
    session_id: str | None = None,
    session_id_inferred: bool = False,
    claude_launcher: str = "claude",
    git_branch: str | None = None,
    git_commit_short: str | None = None,
    git_commit_title: str | None = None,
    git_dirty_added: int = 0,
    git_dirty_deleted: int = 0,
    git_dirty_level: str = "clean",
) -> ContextInfo:
    """Build :class:`ContextInfo` from Claude Code's stdin payload.

    Falls back to ``CLAUDE_PROJECT_DIR`` for ``cwd`` when the stdin hint does
    not include ``workspace.current_dir``. The cc_version is sourced from
    ``version`` (no subprocess call needed). When ``session_id`` is provided,
    it is rendered as a second line in the statusline so the user can copy
    it as ``<launcher> --resume <id>`` (e.g. ``claude --resume <id>`` or
    ``fcc-claude --resume <id>``) in another window.
    """
    cwd = _stdin_cwd(stdin_hint, project_dir_fallback or None)

    cc_version: str | None = None
    if isinstance(stdin_hint, dict):
        version_field = stdin_hint.get("version")
        if isinstance(version_field, str) and version_field:
            cc_version = version_field

    context_used_pct: int | None = None
    if isinstance(stdin_hint, dict):
        context_window = stdin_hint.get("context_window")
        if isinstance(context_window, dict):
            pct = context_window.get("used_percentage")
            if isinstance(pct, (int, float)):
                context_used_pct = int(round(float(pct)))

    session_duration_ms: int | None = None
    if isinstance(stdin_hint, dict):
        cost_field = stdin_hint.get("cost")
        if isinstance(cost_field, dict):
            raw_ms = cost_field.get("total_duration_ms")
            if isinstance(raw_ms, (int, float)) and raw_ms >= 0:
                session_duration_ms = int(raw_ms)

    return ContextInfo(
        cwd=cwd,
        cc_version=cc_version,
        context_used_pct=context_used_pct,
        session_duration_ms=session_duration_ms,
        session_id=session_id,
        session_id_inferred=session_id_inferred,
        claude_launcher=claude_launcher,
        git_branch=git_branch,
        git_commit_short=git_commit_short,
        git_commit_title=git_commit_title,
        git_dirty_lines_added=git_dirty_added,
        git_dirty_lines_deleted=git_dirty_deleted,
        git_dirty_level=git_dirty_level,
    )


def _active_quota_provider(
    totals: TokenTotals,
    fallback_model: str | None,
    std_model: str | None,
    price: ModelPrice | None,
) -> str | None:
    """Return the provider_id that has a live quota adapter, or ``None``.

    Detection order:
      1. Provider prefix parsed from the model id (``openrouter/...``,
         ``deepseek/...``, ``mistral/...``, or bare ``MiniMax-M3``).
      2. The ``provider`` field on the resolved pricing entry (covers bare
         model names like ``deepseek-v4-flash`` that resolve to
         ``provider="deepseek"`` via ``pricing.json``).
      3. **Heuristic:** if the model id looks like a Codex model (``gpt-5``,
         ``gpt-5-codex``, ``o3``, ``o4-mini``, etc.) AND ``~/.codex/auth.json``
         is present (or ``$CODEX_ACCESS_TOKEN`` is set), return
         ``codex_chatgpt`` so the plan badge shows.
      4. **Heuristic:** same Codex-shaped model id but the Codex session is
         NOT active → if ``$OPENAI_API_KEY`` is set, return
         ``openai_dashboard`` so the credit-grants segment shows (admin
         keys only — non-admin keys surface an error and the segment
         is omitted).

    Returns ``None`` for providers without a wired-up adapter (the statusline
    omits the ``⏱`` segment entirely in that case).
    """
    from lib.provider_quota import get_quota_for_provider

    candidate = totals.last_model or fallback_model or std_model
    provider_id: str | None = None
    if candidate:
        derived = _provider_from_model(candidate)
        if derived not in {"anthropic", "unknown"} and get_quota_for_provider(derived):
            # Normalize aliases (e.g. ``codestral`` → ``mistral``).
            provider_id = _normalize_quota_provider_id(derived)
    if provider_id is None and price is not None:
        adapter = get_quota_for_provider(price.provider)
        if adapter is not None:
            provider_id = _normalize_quota_provider_id(price.provider)
    # Bare model id (e.g. ``deepseek-v4-pro``, ``mistral-large-latest``) often
    # resolves to a gateway (``opencode_go``, ``opencode``) in pricing.json —
    # even though the *direct* upstream is DeepSeek or Mistral. Detect the
    # family from the id prefix and re-route to the direct provider.
    if provider_id is None and candidate:
        direct = _direct_provider_for_bare_model(candidate)
        if direct is not None and get_quota_for_provider(direct):
            provider_id = _normalize_quota_provider_id(direct)
    if provider_id is None and _looks_like_codex_model(candidate):
        if _codex_session_active() and get_quota_for_provider("codex_chatgpt"):
            provider_id = "codex_chatgpt"
        elif (
            os.environ.get("OPENAI_API_KEY")
            and get_quota_for_provider("openai_dashboard")
        ):
            provider_id = "openai_dashboard"
    return provider_id


# Direct provider families whose quota API is reachable when the user uses
# the model name *without* a gateway prefix. ``provider`` is the canonical
# name registered in ``QUOTA_PROVIDERS``.
_DIRECT_PROVIDER_MODEL_FAMILIES: tuple[tuple[str, str], ...] = (
    # family_prefix -> provider_id
    ("deepseek-", "deepseek"),
    ("deepseek/", "deepseek"),  # legacy / defensive
    ("mistral-", "mistral"),
    ("mistral/", "mistral"),
    ("codestral-", "mistral"),  # codestral hits the Mistral backend
    ("codestral/", "mistral"),
)


def _direct_provider_for_bare_model(model_id: str) -> str | None:
    """Return the direct-upstream provider for a bare model id, or ``None``.

    The statusline uses this when the pricing entry routes the bare model
    through a gateway (e.g. ``opencode_go``) that has no quota API, while
    the *direct* upstream (DeepSeek, Mistral) does. The match is intentionally
    conservative: only well-known model families are re-routed.
    """
    if not model_id or "/" in model_id:
        # If the model already has a gateway prefix, ``_provider_from_model``
        # has already extracted the correct provider in the caller.
        return None
    model_lower = model_id.lower()
    for prefix, provider_id in _DIRECT_PROVIDER_MODEL_FAMILIES:
        if model_lower.startswith(prefix):
            return provider_id
    return None


def _normalize_quota_provider_id(provider_id: str) -> str:
    """Normalize a provider_id to its canonical quota registry name.

    Currently the only alias is ``codestral`` → ``mistral`` (the fcc-claude
    ``codestral`` gateway hits the same Mistral backend, so its usage is
    surfaced through the Mistral ``/v1/usage`` endpoint). Other ids pass
    through unchanged.
    """
    if provider_id == "codestral":
        return "mistral"
    return provider_id


_CODEX_MODEL_PREFIXES = ("gpt-5", "gpt-4", "o1", "o3", "o4", "o5")
# Codex may also serve bare or hyphenated variants of the form ``gpt-4o``,
# ``gpt-3.5-turbo`` etc. — match anything that starts with ``gpt-`` since all
# OpenAI GPT models are routable through the Codex backend today.
_CODEX_MODEL_FAMILY_PREFIXES = ("gpt-",)


def _looks_like_codex_model(model_id: str | None) -> bool:
    """True if ``model_id`` looks like a model the Codex CLI can serve.

    Recognised shapes: ``gpt-5``, ``gpt-5-codex``, ``gpt-5-mini``, ``gpt-4o``,
    ``gpt-3.5-turbo``, ``o1``, ``o3``, ``o4-mini``, and the bare ``o5`` etc.
    """
    if not model_id:
        return False
    model_lower = model_id.lower()
    if any(
        model_lower.startswith(prefix)
        for prefix in _CODEX_MODEL_FAMILY_PREFIXES
    ):
        return True
    return any(
        model_lower == prefix or model_lower.startswith(prefix + "-")
        for prefix in _CODEX_MODEL_PREFIXES
    )


def _codex_session_active() -> bool:
    """True if the Codex CLI has a usable auth file or env token available.

    An empty ``auth.json`` (``{}``) is treated as *inactive* — only files that
    contain a non-empty ``access_token`` (or ``id_token``) count. This avoids
    surfacing a broken CodexChatgptQuotaProvider when the user created an
    empty placeholder file for some other reason.
    """
    if os.environ.get("CODEX_ACCESS_TOKEN"):
        return True
    codex_home = Path.home() / ".codex"
    auth_path = codex_home / "auth.json"
    if not auth_path.exists():
        return False
    try:
        raw = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    for key in ("access_token", "id_token"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _price_for_model(
    model_id: str | None,
    table: dict[str, ModelPrice],
) -> ModelPrice | None:
    """Look up the price entry for ``model_id`` with gateway fallback.

    For free-claude-code gateway IDs (``anthropic/minimax/MiniMax-M3``) the
    ``anthropic/`` prefix is stripped before lookup, so a price table keyed by
    the direct provider ref (``minimax/MiniMax-M3``) still resolves.
    """
    if model_id is None:
        return table.get("__fallback__")
    direct = table.get(model_id)
    if direct is not None:
        return direct
    stripped = _strip_gateway_prefix(model_id)
    if stripped != model_id:
        stripped_price = table.get(stripped)
        if stripped_price is not None:
            return stripped_price
    return table.get("__fallback__")


def _cwd_cache_path() -> Path:
    """Return the absolute path of the on-disk cwd cache file."""
    return Path.home() / ".cache" / "claude-llm-quota-bar" / CWD_CACHE_FILENAME


def _read_cwd_cache(path: Path) -> str | None:
    """Read the cached cwd if it exists and is younger than the TTL.

    Returns ``None`` on any failure (missing file, parse error, stale age)
    so the caller can fall through to the next layer. We never raise — the
    cache is best-effort.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    cwd = raw.get("cwd")
    ts = raw.get("ts")
    if not isinstance(cwd, str) or not cwd:
        return None
    if not isinstance(ts, (int, float)):
        return None
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        return None
    if age < 0 or age > CWD_CACHE_MAX_AGE_SECONDS:
        return None
    if not Path(cwd).is_dir():
        return None  # the directory disappeared; cache is useless
    return cwd


def _write_cwd_cache(path: Path, cwd: str) -> None:
    """Persist the resolved cwd so the next tick can use it as fallback.

    Atomic write: dump to ``<path>.tmp`` then ``os.replace`` over the
    target so a partial write (process killed mid-flush) cannot leave a
    corrupt JSON file. Failures are swallowed — the cache is best-effort
    and should never break the statusline render.
    """
    payload = {"cwd": cwd, "ts": time.time()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Best-effort: a failed cache write is not fatal.
        return


def _discover_cwd_via_lsof() -> str | None:
    """Discover the cwd of the Claude Code process via ``lsof`` (macOS).

    The Claude Code TUI re-spawns the statusline command on every refresh
    tick, so the script's parent PID is the shell that launched Claude
    Code (Terminal.app, iTerm2, etc.), not Claude Code itself. Walking
    further up the process tree via ``ps`` is unreliable across launchers
    (Terminal.app spawns login → zsh → claude via a long chain), so we
    use ``lsof`` to find the process that actually opened the
    ``settings.json`` file we know Claude Code reads. If that file is
    currently open by some Claude Code process, we ask lsof for its cwd.

    This is macOS-only (``lsof -p <pid> -d cwd -F n``). On other
    platforms we return ``None`` and the caller falls through to the
    placeholder.
    """
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return None
    try:
        # Find which process has the file open. ``-t`` prints only PIDs.
        # We use ``-F p`` (machine-readable) to be safe against pathological
        # PIDs in weird locales, but ``-t`` is shorter and works on stock
        # macOS — both paths are validated by the try/except below.
        result = subprocess.run(
            ["lsof", "-t", str(settings_path)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        pid_str = line.strip()
        if not pid_str:
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        # Now ask lsof for that process's cwd.
        try:
            cwd_result = subprocess.run(
                ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-F", "n"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if cwd_result.returncode != 0:
            continue
        # Output looks like: ``p<PID>\nc/<path>\n``; we want the ``c/`` line.
        for entry in cwd_result.stdout.splitlines():
            if entry.startswith("c/"):
                path = entry[2:].strip()
                if path and Path(path).is_dir():
                    return path
    return None


def _resolve_cwd(env_value: str | None, cache_path: Path) -> tuple[str | None, str]:
    """Resolve the cwd using a layered fallback.

    Resolution order:

    1. **Env** — return ``env_value`` when it points to an existing
       directory. Cache the result for the next tick. This is the
       happy path; the script spends <1 ms here.
    2. **Cache** — read the on-disk cache written by a previous tick.
       Skipped when the cache is older than :data:`CWD_CACHE_MAX_AGE_SECONDS`
       or points at a directory that no longer exists.
    3. **lsof** — best-effort discovery of the Claude Code process cwd
       via macOS ``lsof``. Skipped on non-Darwin platforms.
    4. **None** — give up; the caller renders the
       :data:`NO_SESSION_PLACEHOLDER` with the appropriate tag.

    Returns ``(cwd_or_None, tag)`` so the caller can surface which
    layer ended up answering the question (handy for diagnostics and
    the inline placeholder).
    """
    if env_value:
        if Path(env_value).is_dir():
            _write_cwd_cache(cache_path, env_value)
            return env_value, CWD_TAG_ENV
    cached = _read_cwd_cache(cache_path)
    if cached is not None:
        return cached, CWD_TAG_CACHE
    discovered = _discover_cwd_via_lsof()
    if discovered is not None:
        _write_cwd_cache(cache_path, discovered)
        return discovered, CWD_TAG_LSOF
    return None, CWD_TAG_NONE


def main() -> int:
    started = time.perf_counter()
    try:
        return _main_impl(started)
    except Exception:
        # Any unhandled exception would blank the statusline bar entirely —
        # Claude Code's subprocess runner swallows stderr, so the user sees
        # nothing.  Print a graceful fallback with the exception type so the
        # user at least knows the bar is alive and can report the error.
        exc_name = sys.exc_info()[0].__name__ if sys.exc_info()[0] else "?"
        print(
            f"{NO_SESSION_PLACEHOLDER} \x1b[2m(erro: {exc_name})\x1b[0m",
            flush=True,
        )
        return 1


def _main_impl(started: float) -> int:
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", DEFAULT_CLAUDE_DIR))
    # Resolve the cwd with a layered fallback. The env var is the happy
    # path (< 1 ms); the cache + lsof layers exist so we keep working
    # when Claude Code forgets to export ``CLAUDE_PROJECT_DIR`` (a known
    # flaky behaviour — see CHANGELOG for the regression that motivated
    # this). ``project_dir`` ends up the resolved cwd or ``""`` when every
    # layer gives up; the downstream ``_safe_log_path`` already handles
    # the empty case by returning ``no_jsonls``.
    project_dir, cwd_tag = _resolve_cwd(
        os.environ.get("CLAUDE_PROJECT_DIR", ""),
        _cwd_cache_path(),
    )
    project_dir = project_dir or ""
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")

    pricing_path = THIS_DIR / "pricing.json"
    config_path = THIS_DIR / "statusline.env.json"

    if not pricing_path.exists():
        print(PLACEHOLDER + " (pricing.json ausente)", file=sys.stdout)
        return 0

    table, fallback_fx = load_pricing_table(pricing_path)
    opts = _load_display_options(config_path)
    fx_ttl = float(opts.fx_cache_ttl_seconds or DEFAULT_TTL_SECONDS)
    fx = resolve_rate(fallback_rate=fallback_fx, cache_ttl_seconds=fx_ttl)
    fx_source = fx.source

    stdin_hint = _read_stdin()
    std_model = None
    if isinstance(stdin_hint, dict):
        model_field = stdin_hint.get("model")
        if isinstance(model_field, dict):
            std_model = model_field.get("id") or model_field.get("display_name")
        elif isinstance(model_field, str):
            std_model = model_field
    if std_model is None:
        std_model = os.environ.get("CLAUDE_MODEL")

    log_path, resolved_session_id, resolution_tag, session_id_inferred = _safe_log_path(
        claude_dir, project_dir, session_id
    )
    if log_path is None:
        _debug_dump({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "env": _debug_env_summary(),
            "resolution": resolution_tag,
            "log_path": None,
            "placeholder": NO_SESSION_PLACEHOLDER,
        }, force=True)
        # Render the reason inline so the user can diagnose from the
        # statusline itself (no need to cat the debug file). Cheap — the
        # tag is a short string set by _safe_log_path.
        print(f"{NO_SESSION_PLACEHOLDER} · {resolution_tag}", flush=True)
        return 0
    _debug_dump({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "env": _debug_env_summary(),
        "resolution": resolution_tag,
        "log_path": str(log_path),
        "log_size": _safe_file_size(log_path),
    })
    from lib.parser import aggregate_session, parse_first_response_model

    fallback_model = parse_first_response_model(log_path) if resolution_tag == "fallback" else None
    totals = _aggregate_cached(log_path, session_id or "")
    last_model = totals.last_model or fallback_model or std_model
    if fallback_model and totals.request_count == 0:
        last_model = fallback_model
    if last_model and last_model != totals.last_model:
        totals = TokenTotals(
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cache_creation_tokens=totals.cache_creation_tokens,
            cache_read_tokens=totals.cache_read_tokens,
            request_count=totals.request_count,
            first_timestamp=totals.first_timestamp,
            last_timestamp=totals.last_timestamp,
            last_model=last_model,
            last_provider=_provider_from_model(last_model),
        )
    price = _price_for_model(last_model, table)
    cost = compute_cost(totals, table, fx.rate)

    # Resolve git metadata (branch + last commit) for the resolved cwd.
    # Use the same CWD that _build_context_info will use — stdin hint first,
    # then the env/cache/lsof fallback. This prevents a mismatch where the
    # statusline shows the correct folder (from stdin) but resolve_git sees
    # an empty string (env var unset on this tick) and renders [sem git].
    git_cwd = _stdin_cwd(stdin_hint, project_dir or None)
    git_info = resolve_git(git_cwd)

    # Classify working-tree dirtyness so the render layer can pick the
    # right colour. Thresholds come from DisplayOptions (defaults 50/300,
    # overridable via statusline.env.json).
    dirty_total = git_info.dirty_added + git_info.dirty_deleted
    if dirty_total >= opts.git_dirty_alert_lines:
        git_dirty_level = "alert"
    elif dirty_total >= opts.git_dirty_warn_lines:
        git_dirty_level = "warn"
    else:
        git_dirty_level = "clean"

    context = _build_context_info(
        stdin_hint,
        project_dir,
        session_id=resolved_session_id,
        session_id_inferred=session_id_inferred,
        claude_launcher=_detect_claude_launcher(),
        git_branch=git_info.branch,
        git_commit_short=git_info.commit_short,
        git_commit_title=git_info.commit_title,
        git_dirty_added=git_info.dirty_added,
        git_dirty_deleted=git_info.dirty_deleted,
        git_dirty_level=git_dirty_level,
    )
    quota = None
    quota_provider_id = _active_quota_provider(
        totals, fallback_model, std_model, price
    )
    if opts.show_provider_quota and quota_provider_id:
        quota = fetch_quota(quota_provider_id)

    # When the JSONL has no assistant entries yet, derive provider from the
    # active model id (stdin or env) so the model label shows the real
    # upstream provider, not "anthropic" from the gateway prefix.
    if totals.last_provider in (None, "anthropic", "unknown"):
        candidate = totals.last_model or std_model
        if candidate:
            derived = _provider_from_model(candidate)
            if derived and derived not in ("anthropic", "unknown"):
                totals = TokenTotals(
                    input_tokens=totals.input_tokens,
                    output_tokens=totals.output_tokens,
                    cache_creation_tokens=totals.cache_creation_tokens,
                    cache_read_tokens=totals.cache_read_tokens,
                    request_count=totals.request_count,
                    first_timestamp=totals.first_timestamp,
                    last_timestamp=totals.last_timestamp,
                    last_model=totals.last_model,
                    last_provider=derived,
                )

    line = render(totals, cost, price, opts, context=context, quota=quota)
    if fx_source == "fallback":
        line = line + " \x1b[2m(fx=fallback)\x1b[0m"
    elif fx_source == "cache" and fx.age_seconds > fx_ttl:
        line = line + f" \x1b[2m(fx={fx.age_seconds / 3600:.1f}h)\x1b[0m"
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > 100:
        line = line + f"  \x1b[2m({elapsed_ms:.0f}ms)\x1b[0m"
    print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
