"""Render aggregated token totals and cost into a statusline string.

The Claude Code statusline protocol expects the script to print a single line
to stdout. ANSI color codes are supported (the Claude Code TUI renders them).

Public entry point: :func:`render`. The function takes parsed token totals,
a cost breakdown, and a few display options, and returns the final string.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .parser import TokenTotals
from .pricing import CostBreakdown, ModelPrice

ColorMode = Literal["auto", "always", "never"]

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"

CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
MAGENTA = "\x1b[35m"
BLUE = "\x1b[34m"
GRAY = "\x1b[90m"


@dataclass(frozen=True, slots=True)
class DisplayOptions:
    """Toggles for which fields appear in the statusline."""

    show_provider: bool = True
    show_model: bool = True
    show_tokens: bool = True
    show_cost: bool = True
    show_duration: bool = True
    show_burn_rate: bool = True
    show_cache_pct: bool = True
    show_flags: bool = True
    show_both_currencies: bool = True
    verbose: bool = False
    color: ColorMode = "auto"
    cost_warn_brl: float = 0.50
    cost_alert_brl: float = 2.50
    burn_warn_per_min: int = 1500
    burn_alert_per_min: int = 5000
    fx_cache_ttl_seconds: float = 3600.0


FLAG_BR = "\U0001F1E7\U0001F1F7"  # Brazil
FLAG_US = "\U0001F1FA\U0001F1F8"  # United States


def _use_color(mode: ColorMode) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return True


def _colorize(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{color}{text}{RESET}"


def _format_tokens(n: int) -> str:
    """Format integer token count as compact ``1.2k`` / ``12k`` / ``3.4M``."""
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1_000_000:.1f}M"


def _format_cost(usd: float, fx: float) -> tuple[str, str]:
    """Return ``(usd_str, brl_str)`` formatted for compact display."""
    if usd < 0.01:
        usd_str = "$0.00"
    elif usd < 1:
        usd_str = f"${usd:.3f}"
    else:
        usd_str = f"${usd:.2f}"
    brl = usd * fx
    if brl < 0.01:
        brl_str = "R$0.00"
    elif brl < 1:
        brl_str = f"R${brl:.3f}"
    else:
        brl_str = f"R${brl:.2f}"
    return usd_str, brl_str


def _format_duration(start: str | None, end: str | None) -> str | None:
    """Return compact duration like ``18m`` / ``1h23m`` / ``42s``."""
    if not start or not end:
        return None
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = t1 - t0
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return None
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    hours, rem = divmod(total_seconds, 3600)
    return f"{hours}h{rem // 60}m"


def _burn_rate_color(rate: float, opts: DisplayOptions) -> str:
    if rate >= opts.burn_alert_per_min:
        return RED
    if rate >= opts.burn_warn_per_min:
        return YELLOW
    return GREEN


def _cost_color(brl: float, opts: DisplayOptions) -> str:
    if brl >= opts.cost_alert_brl:
        return RED
    if brl >= opts.cost_warn_brl:
        return YELLOW
    return GREEN


def render(
    totals: TokenTotals,
    cost: CostBreakdown,
    price: ModelPrice | None,
    opts: DisplayOptions | None = None,
) -> str:
    """Build the final statusline string."""
    if opts is None:
        opts = DisplayOptions()
    use_color = _use_color(opts.color)
    parts: list[str] = []

    if opts.show_model:
        model_label = price.display if price else (totals.last_model or "???")
        if totals.last_provider and totals.last_provider not in {"anthropic", "unknown"}:
            model_label = f"{model_label}·{totals.last_provider}"
        if cost.unknown_models:
            model_label = f"{model_label}?"
        parts.append(_colorize(f"[{model_label}]", CYAN, use_color))

    if opts.show_tokens:
        in_t = _format_tokens(totals.input_tokens)
        out_t = _format_tokens(totals.output_tokens)
        cache_t = _format_tokens(
            totals.cache_read_tokens + totals.cache_creation_tokens
        )
        parts.append(
            _colorize(f"\u2b06{in_t}", BLUE, use_color)
            + " "
            + _colorize(f"\u2b07{out_t}", MAGENTA, use_color)
            + " "
            + _colorize(f"\u21bb{cache_t}", GRAY, use_color)
        )

    if opts.show_cost and price is not None:
        usd_str, brl_str = _format_cost(cost.total_cost_usd, cost.fx_to_brl)
        billing = cost.billing_modes.get(price.display, "pay_as_you_go")
        brl_flag = f"{FLAG_BR} " if opts.show_flags else ""
        usd_flag = f"{FLAG_US} " if opts.show_flags else ""

        if billing == "free_tier":
            label = f"{brl_flag}R$0.00 (free)"
            parts.append(_colorize(label, GRAY, use_color))
        elif billing == "token_plan":
            label = f"{brl_flag}R$0.00 (quota)"
            parts.append(_colorize(label, DIM + YELLOW, use_color))
        else:
            color = _cost_color(cost.total_cost_brl, opts)
            if opts.show_both_currencies and cost.total_cost_usd >= 0.0001:
                label = f"{brl_flag}{brl_str} {usd_flag}{usd_str}"
            else:
                label = f"{brl_flag}{brl_str}"
            parts.append(_colorize(label, color, use_color))

    duration = _format_duration(totals.first_timestamp, totals.last_timestamp)
    if opts.show_duration and duration:
        parts.append(_colorize(duration, GRAY, use_color))

    burn_rate: float | None = None
    if opts.show_burn_rate and duration and totals.total_tokens > 0:
        active_tokens = totals.input_tokens + totals.output_tokens
        if duration.endswith("s") and not duration.endswith("ms"):
            minutes = max(int(duration[:-1]) / 60, 1 / 60)
        elif duration.endswith("m"):
            minutes = max(int(duration[:-1]), 1)
        elif duration.endswith("h"):
            h = int(duration.split("h")[0])
            rem = duration.split("h")[1]
            minutes = h * 60 + (int(rem[:-1]) if rem.endswith("m") else 0)
        else:
            minutes = 1
        burn_rate = active_tokens / minutes if active_tokens > 0 else 0.0
        rate_str = f"{int(burn_rate)}t/m"
        if burn_rate >= opts.burn_alert_per_min:
            rate_str = f"\u26a0 {rate_str}"
        parts.append(
            _colorize(rate_str, _burn_rate_color(burn_rate, opts), use_color)
        )

    if opts.verbose and price is not None:
        if not opts.show_both_currencies:
            usd_str, brl_str = _format_cost(cost.total_cost_usd, cost.fx_to_brl)
            parts.append(_colorize(f"{FLAG_US} {usd_str}", DIM, use_color))
        if totals.cache_read_tokens + totals.cache_creation_tokens > 0:
            cache_total = totals.cache_read_tokens + totals.cache_creation_tokens
            pct = cache_total / max(totals.total_tokens, 1) * 100
            if opts.show_cache_pct and pct >= 50:
                parts.append(
                    _colorize(f"cache:{pct:.0f}%", DIM + GREEN, use_color)
                )

    separator = _colorize(" \u2022 ", DIM, use_color)
    return separator.join(parts) if parts else _colorize("(empty)", DIM, use_color)
