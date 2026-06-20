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
import sys
import time
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from lib.display import ContextInfo, DisplayOptions, render  # noqa: E402
from lib.fx import DEFAULT_TTL_SECONDS, resolve_rate  # noqa: E402
from lib.minimax_quota import fetch_minimax_quota  # noqa: E402
from lib.parser import (  # noqa: E402
    TokenTotals,
    _provider_from_model,
    _strip_gateway_prefix,
    locate_latest_log,
    locate_session_log,
    parse_first_response_model,
)
from lib.pricing import (  # noqa: E402
    CostBreakdown,
    ModelPrice,
    compute_cost,
    load_pricing_table,
)

DEFAULT_CLAUDE_DIR = Path.home() / ".claude"
PLACEHOLDER = "[statusline: inicializando]"


def _load_display_options(config_path: Path) -> DisplayOptions:
    """Load display toggles from ``statusline.env.json`` if present."""
    if not config_path.exists():
        return DisplayOptions()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DisplayOptions()
    allowed = {f for f in DisplayOptions.__dataclass_fields__}
    kwargs = {k: v for k, v in raw.items() if k in allowed}
    return DisplayOptions(**kwargs)


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


def _safe_log_path(claude_dir: Path, project_dir: str, session_id: str) -> tuple[Path | None, str | None]:
    """Locate the JSONL path for the given session, falling back if needed."""
    path = locate_session_log(claude_dir, project_dir, session_id)
    if path is not None:
        return path, None
    fallback = locate_latest_log(claude_dir, project_dir)
    if fallback is None:
        return None, None
    fallback_model = parse_first_response_model(fallback)
    return fallback, fallback_model


def _build_context_info(
    stdin_hint: dict[str, Any],
    project_dir_fallback: str,
) -> ContextInfo:
    """Build :class:`ContextInfo` from Claude Code's stdin payload.

    Falls back to ``CLAUDE_PROJECT_DIR`` for ``cwd`` when the stdin hint does
    not include ``workspace.current_dir``. The cc_version is sourced from
    ``version`` (no subprocess call needed).
    """
    cwd: str | None = None
    workspace = stdin_hint.get("workspace") if isinstance(stdin_hint, dict) else None
    if isinstance(workspace, dict):
        cwd = workspace.get("current_dir") or workspace.get("project_dir")
    if not cwd and isinstance(stdin_hint, dict):
        cwd = stdin_hint.get("cwd")
    if not cwd:
        cwd = project_dir_fallback or None

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

    return ContextInfo(
        cwd=cwd,
        cc_version=cc_version,
        context_used_pct=context_used_pct,
    )


def _is_minimax_active(
    totals: TokenTotals,
    fallback_model: str | None,
    std_model: str | None,
) -> bool:
    """True when the active model for this statusline refresh is MiniMax."""
    candidate = totals.last_model or fallback_model or std_model
    if not candidate:
        return False
    return _provider_from_model(candidate) == "minimax"


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


def main() -> int:
    started = time.perf_counter()
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", DEFAULT_CLAUDE_DIR))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
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

    log_path, fallback_model = _safe_log_path(claude_dir, project_dir, session_id)
    if log_path is None:
        price = _price_for_model(std_model, table)
        totals = TokenTotals()
        cost = CostBreakdown(fx_to_brl=fx.rate)
    else:
        from lib.parser import aggregate_session

        totals = aggregate_session(log_path, session_id or "")
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

    context = _build_context_info(stdin_hint, project_dir)
    quota = None
    if opts.show_minimax_quota and _is_minimax_active(totals, fallback_model, std_model):
        quota = fetch_minimax_quota()

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
