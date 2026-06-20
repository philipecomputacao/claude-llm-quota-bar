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

from lib.display import DisplayOptions, render  # noqa: E402
from lib.fx import DEFAULT_TTL_SECONDS, resolve_rate  # noqa: E402
from lib.parser import (  # noqa: E402
    TokenTotals,
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


def _price_for_model(
    model_id: str | None,
    table: dict[str, ModelPrice],
) -> ModelPrice | None:
    if model_id is None:
        return table.get("__fallback__")
    return table.get(model_id) or table.get("__fallback__")


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
                last_provider=(
                    last_model.split("/", 1)[0] if "/" in last_model else "anthropic"
                ),
            )
        price = _price_for_model(last_model, table)
        cost = compute_cost(totals, table, fx.rate)

    line = render(totals, cost, price, opts)
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
