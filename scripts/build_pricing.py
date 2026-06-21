#!/usr/bin/env python3
"""Generate pricing.json covering every model exposed by the FCC proxy.

Queries ``/v1/models`` and ``/admin/api/providers/<id>/test`` to enumerate every
model the user has access to, then classifies each one into a pricing tier.

Usage::

    python3 scripts/build_pricing.py [--out pricing.json] [--host http://localhost:<port>]

Auth: the script reads ``$FREE_CC_AUTH_TOKEN`` and falls back to ``"freecc"``
(the FCC dev default — only valid when the local proxy has not been secured).
Override the env var when running against a non-default install.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_HOST = "http://localhost:8082"
DEFAULT_AUTH_TOKEN = "freecc"


def _resolve_auth_token() -> str:
    """Return the FCC proxy auth token, preferring env over the dev default."""
    return os.environ.get("FREE_CC_AUTH_TOKEN") or DEFAULT_AUTH_TOKEN


AUTH_TOKEN = _resolve_auth_token()

PROVIDER_ORDER = (
    "minimax",
    "opencode_go",
    "opencode",
    "deepseek",
    "open_router",
    "anthropic",
)

# Tier pricing: per-million USD. ``cache_write`` defaults to input price (close
# enough for Anthropic-compat providers; some are explicitly priced).
TIERS: dict[str, dict[str, float | str]] = {
    # tier -> input / output / cache_read / cache_write
    "minimax-m3":     {"input": 0.21, "output": 0.84, "cache_read": 0.02, "cache_write": 0.21},
    "minimax-m2.7":   {"input": 0.15, "output": 0.60, "cache_read": 0.015, "cache_write": 0.15},
    "minimax-m2.5":   {"input": 0.10, "output": 0.40, "cache_read": 0.01, "cache_write": 0.10},
    "minimax-m2":     {"input": 0.07, "output": 0.28, "cache_read": 0.007, "cache_write": 0.07},
    "anthropic-opus": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "anthropic-sonnet": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "anthropic-haiku":  {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "gpt-5-pro":     {"input": 15.00, "output": 120.00, "cache_read": 1.50, "cache_write": 15.00},
    "gpt-5":         {"input": 2.50, "output": 10.00, "cache_read": 0.25, "cache_write": 2.50},
    "gpt-5-mini":    {"input": 0.25, "output": 2.00, "cache_read": 0.025, "cache_write": 0.25},
    "gpt-5-nano":    {"input": 0.05, "output": 0.40, "cache_read": 0.005, "cache_write": 0.05},
    "deepseek":      {"input": 0.27, "output": 1.10, "cache_read": 0.07, "cache_write": 0.27},
    "qwen-large":    {"input": 0.40, "output": 1.60, "cache_read": 0.04, "cache_write": 0.40},
    "qwen-medium":   {"input": 0.20, "output": 0.80, "cache_read": 0.02, "cache_write": 0.20},
    "glm-large":     {"input": 0.50, "output": 2.00, "cache_read": 0.05, "cache_write": 0.50},
    "kimi":          {"input": 0.15, "output": 2.50, "cache_read": 0.015, "cache_write": 0.15},
    "mimo":          {"input": 0.10, "output": 0.40, "cache_read": 0.01, "cache_write": 0.10},
    "gemini-pro":    {"input": 1.25, "output": 10.00, "cache_read": 0.125, "cache_write": 1.25},
    "gemini-flash":  {"input": 0.075, "output": 0.30, "cache_read": 0.008, "cache_write": 0.075},
    "gemini-flash-lite": {"input": 0.025, "output": 0.10, "cache_read": 0.0025, "cache_write": 0.025},
    "nova-pro":      {"input": 0.80, "output": 3.20, "cache_read": 0.08, "cache_write": 0.80},
    "nova-lite":     {"input": 0.06, "output": 0.24, "cache_read": 0.006, "cache_write": 0.06},
    "nova-micro":    {"input": 0.035, "output": 0.14, "cache_read": 0.0035, "cache_write": 0.035},
    "cohere":        {"input": 0.50, "output": 2.00, "cache_read": 0.05, "cache_write": 0.50},
    "ai21":          {"input": 1.00, "output": 4.00, "cache_read": 0.10, "cache_write": 1.00},
    "grok":          {"input": 5.00, "output": 15.00, "cache_read": 0.50, "cache_write": 5.00},
    "free":          {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    "unknown":       {"input": 1.00, "output": 3.00, "cache_read": 0.10, "cache_write": 1.00},
}


def http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"x-api-key": AUTH_TOKEN})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url: str) -> Any:
    req = urllib.request.Request(
        url, data=b"{}", headers={"Content-Type": "application/json", "x-api-key": AUTH_TOKEN}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def collect_models(host: str) -> dict[str, list[str]]:
    """Return provider -> list[model_id] for every provider that responds OK."""
    out: dict[str, list[str]] = {}
    providers = [
        "minimax",
        "opencode",
        "opencode_go",
        "deepseek",
        "open_router",
        "nvidia_nim",
        "gemini",
        "mistral",
        "mistral_codestral",
        "wafer",
        "kimi",
        "cerebras",
        "groq",
        "fireworks",
        "zai",
    ]
    for prov in providers:
        try:
            data = http_post_json(f"{host}/admin/api/providers/{prov}/test")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        if data.get("ok") and isinstance(data.get("models"), list):
            out[prov] = sorted(set(data["models"]))
    return out


def classify(provider: str, model_id: str) -> dict[str, Any]:
    """Pick a pricing tier for a single model."""
    is_free = "-free" in model_id.lower() or model_id.lower().endswith(":free")
    model_lower = model_id.lower()

    if provider == "minimax":
        if "m3" in model_lower:
            tier = "minimax-m3"
        elif "m2.7" in model_lower:
            tier = "minimax-m2.7"
        elif "m2.5" in model_lower:
            tier = "minimax-m2.5"
        elif "m2" in model_lower:
            tier = "minimax-m2"
        else:
            tier = "minimax-m2.5"
        return _entry(tier, "minimax", _strip_minimax(model_id), "pay_as_you_go")

    if provider in ("opencode", "opencode_go"):
        if is_free:
            return _entry(
                "free",
                provider,
                _strip_model_id(model_id),
                "free_tier",
                notes="Free tier on OpenCode Zen/Go.",
            )
        if re.search(r"claude[-_.]?opus", model_lower):
            tier = "anthropic-opus"
        elif re.search(r"claude[-_.]?sonnet", model_lower):
            tier = "anthropic-sonnet"
        elif re.search(r"claude[-_.]?haiku", model_lower):
            tier = "anthropic-haiku"
        elif re.search(r"claude[-_.]?fable", model_lower):
            tier = "anthropic-sonnet"
        elif re.search(r"gpt-5\.(4|5|3|2|1|0)[-_.]?(pro|codex|max)?", model_lower):
            if "pro" in model_lower and "mini" not in model_lower:
                tier = "gpt-5-pro"
            elif "nano" in model_lower:
                tier = "gpt-5-nano"
            else:
                tier = "gpt-5"
        elif re.search(r"gpt-5[-_.]?(nano|mini)", model_lower):
            tier = "gpt-5-nano" if "nano" in model_lower else "gpt-5-mini"
        elif re.search(r"deepseek[-_.]?v[34]", model_lower):
            tier = "deepseek"
        elif re.search(r"gemini[-_.]?3[-_.]?pro", model_lower):
            tier = "gemini-pro"
        elif re.search(r"gemini[-_.]?(2\.5|3)", model_lower):
            tier = "gemini-flash"
        elif re.search(r"gemini[-_.]?flash[-_.]?lite", model_lower):
            tier = "gemini-flash-lite"
        elif re.search(r"qwen[-_.]?(3\.7|3\.6|3\.5)", model_lower):
            if "plus" in model_lower or "max" in model_lower:
                tier = "qwen-large"
            else:
                tier = "qwen-medium"
        elif re.search(r"glm[-_.]?5", model_lower):
            tier = "glm-large"
        elif re.search(r"kimi[-_.]?k?2", model_lower):
            tier = "kimi"
        elif re.search(r"mimo", model_lower):
            tier = "mimo"
        elif re.search(r"minimax", model_lower):
            tier = "minimax-m2.7" if "2.7" in model_lower else "minimax-m2.5"
        elif re.search(r"nemotron", model_lower):
            tier = "free"
        elif re.search(r"grok", model_lower):
            tier = "grok"
        elif re.search(r"north", model_lower):
            tier = "free"
        elif re.search(r"big[-_.]?pickle", model_lower):
            tier = "free"
        else:
            tier = "unknown"
        return _entry(tier, provider, _strip_model_id(model_id), "pay_as_you_go")

    if provider == "deepseek":
        return _entry("deepseek", "deepseek", model_id, "pay_as_you_go")

    if provider == "open_router":
        return _classify_openrouter(model_id)

    return _entry("unknown", provider, model_id, "unknown")


def _classify_openrouter(model_id: str) -> dict[str, Any]:
    """Best-effort tier for OpenRouter models."""
    ml = model_id.lower()
    is_free = ml.endswith(":free")

    if is_free:
        return _entry("free", "open_router", model_id, "free_tier")

    if "claude" in ml:
        if "opus" in ml:
            return _entry("anthropic-opus", "open_router", model_id, "pay_as_you_go")
        if "sonnet" in ml:
            return _entry("anthropic-sonnet", "open_router", model_id, "pay_as_you_go")
        if "haiku" in ml:
            return _entry("anthropic-haiku", "open_router", model_id, "pay_as_you_go")

    if "gemini" in ml:
        if "pro" in ml or "3" in ml:
            return _entry("gemini-pro", "open_router", model_id, "pay_as_you_go")
        if "flash-lite" in ml or "lite" in ml:
            return _entry("gemini-flash-lite", "open_router", model_id, "pay_as_you_go")
        return _entry("gemini-flash", "open_router", model_id, "pay_as_you_go")

    if "gpt-5" in ml:
        if "pro" in ml:
            return _entry("gpt-5-pro", "open_router", model_id, "pay_as_you_go")
        if "nano" in ml:
            return _entry("gpt-5-nano", "open_router", model_id, "pay_as_you_go")
        if "mini" in ml:
            return _entry("gpt-5-mini", "open_router", model_id, "pay_as_you_go")
        return _entry("gpt-5", "open_router", model_id, "pay_as_you_go")

    if "deepseek" in ml:
        return _entry("deepseek", "open_router", model_id, "pay_as_you_go")

    if "qwen" in ml:
        if "max" in ml or "plus" in ml:
            return _entry("qwen-large", "open_router", model_id, "pay_as_you_go")
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")

    if "llama" in ml or "meta-llama" in ml:
        return _entry("unknown", "open_router", model_id, "pay_as_you_go")

    if "nova" in ml:
        if "premier" in ml or "pro" in ml:
            return _entry("nova-pro", "open_router", model_id, "pay_as_you_go")
        if "lite" in ml:
            return _entry("nova-lite", "open_router", model_id, "pay_as_you_go")
        return _entry("nova-micro", "open_router", model_id, "pay_as_you_go")

    if "command" in ml or "cohere" in ml:
        return _entry("cohere", "open_router", model_id, "pay_as_you_go")

    if "jamba" in ml or "ai21" in ml:
        return _entry("ai21", "open_router", model_id, "pay_as_you_go")

    if "grok" in ml:
        return _entry("grok", "open_router", model_id, "pay_as_you_go")

    if "mistral" in ml or "mixtral" in ml or "codestral" in ml:
        if "large" in ml:
            return _entry("glm-large", "open_router", model_id, "pay_as_you_go")
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")

    if "kimi" in ml:
        return _entry("kimi", "open_router", model_id, "pay_as_you_go")

    if "minimax" in ml:
        if "m3" in ml:
            return _entry("minimax-m3", "open_router", model_id, "pay_as_you_go")
        if "m2.7" in ml:
            return _entry("minimax-m2.7", "open_router", model_id, "pay_as_you_go")
        return _entry("minimax-m2.5", "open_router", model_id, "pay_as_you_go")

    # OpenAI family (o1/o3/o4 are reasoning; gpt-4 family similar to gpt-5-mini).
    if re.search(r"\bo[1-9](-pro|-mini)?\b", ml) or "deep-research" in ml:
        return _entry("gpt-5-pro", "open_router", model_id, "pay_as_you_go")
    if "gpt-4o-mini" in ml or "gpt-4.1-mini" in ml or "gpt-4.1-nano" in ml or "gpt-3.5" in ml:
        return _entry("gpt-5-mini", "open_router", model_id, "pay_as_you_go")
    if "gpt-4" in ml or "gpt-audio" in ml or "gpt-chat" in ml or "gpt-oss" in ml:
        return _entry("gpt-5-mini", "open_router", model_id, "pay_as_you_go")

    # Z.ai GLM family (model vendor 'z-ai' is OpenRouter namespace for Z.ai).
    if "z-ai" in ml or "glm" in ml:
        if "5" in ml:
            return _entry("glm-large", "open_router", model_id, "pay_as_you_go")
        return _entry("glm-large", "open_router", model_id, "pay_as_you_go")

    # Special OpenRouter selectors.
    if ml.endswith("/auto") or ml.endswith("/free") or "owl-alpha" in ml:
        return _entry("free", "open_router", model_id, "free_tier")
    if "~" in model_id:
        # Latest aliases (e.g. ~openai/gpt-latest).
        if "anthropic" in ml:
            return _entry("anthropic-sonnet", "open_router", model_id, "pay_as_you_go")
        if "openai" in ml:
            return _entry("gpt-5", "open_router", model_id, "pay_as_you_go")
        return _entry("unknown", "open_router", model_id, "pay_as_you_go")

    # Xiaomi mimo family.
    if "mimo" in ml:
        return _entry("mimo", "open_router", model_id, "pay_as_you_go")

    # Tencent hy3 (preview models).
    if "hy3" in ml or "tencent" in ml:
        return _entry("qwen-large", "open_router", model_id, "pay_as_you_go")

    # Long-tail vendors (best-effort qwen-medium).
    if "gemma" in ml or "nemotron" in ml or "llama" in ml or "granite" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "arcee" in ml or "trinity" in ml or "virtuoso" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "kwaipilot" in ml or "kat-coder" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "poolside" in ml or "laguna" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "prime-intellect" in ml or "intellect" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "rekaai" in ml or "relace" in ml or "sao10k" in ml or "l3.1" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "stepfun" in ml or "step-" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "upstage" in ml or "solar" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "thedrummer" in ml or "rocinante" in ml or "unslopnemo" in ml:
        return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go")
    if "claude-fable" in ml:
        return _entry("anthropic-sonnet", "open_router", model_id, "pay_as_you_go")

    # Long-tail fallback (best-effort estimate).
    return _entry("qwen-medium", "open_router", model_id, "pay_as_you_go",
                  notes="Preco estimado. Vendor nao classificado - revisar manualmente.")


def _entry(
    tier: str,
    provider: str,
    display: str,
    billing_mode: str,
    notes: str = "",
) -> dict[str, Any]:
    prices = TIERS[tier]
    entry: dict[str, Any] = {
        "provider": provider,
        "display": display,
        "input": prices["input"],
        "output": prices["output"],
        "cache_read": prices["cache_read"],
        "cache_write": prices["cache_write"],
        "unit": "per_million_tokens",
        "billing_mode": billing_mode,
        "tier": tier,
    }
    if notes:
        entry["notes"] = notes
    return entry


def _strip_minimax(model_id: str) -> str:
    """Map MiniMax model ids to canonical display (M3, M2.7, M2.5, ...)."""
    ml = model_id.lower()
    if "m3" in ml:
        base = "MiniMax-M3"
    elif "m2.7" in ml:
        base = "MiniMax-M2.7"
    elif "m2.5" in ml:
        base = "MiniMax-M2.5"
    elif "m2.1" in ml:
        base = "MiniMax-M2.1"
    elif "m2" in ml:
        base = "MiniMax-M2"
    else:
        base = model_id
    if "highspeed" in ml:
        return f"{base}-highspeed"
    return base


def _strip_model_id(model_id: str) -> str:
    """Best-effort human-readable display label from a raw model id."""
    return model_id.replace("_", "-")


def build_pricing(host: str) -> dict[str, Any]:
    providers = collect_models(host)
    merged: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}

    for prov in PROVIDER_ORDER:
        for model_id in providers.get(prov, []):
            key = f"{prov}/{model_id}"
            entry = classify(prov, model_id)
            sources.setdefault(key, []).append(prov)
            if key not in merged:
                merged[key] = entry
            else:
                # Prefer free_tier over pay_as_you_go when ambiguous.
                if merged[key]["billing_mode"] == "pay_as_you_go" and entry["billing_mode"] == "free_tier":
                    merged[key] = entry

    # Add unprefixed aliases so the statusline can resolve Anthropic-style model
    # ids that Claude Code logs without a provider prefix (e.g. "claude-sonnet-4-6").
    for prov in PROVIDER_ORDER:
        for model_id in list(providers.get(prov, [])):
            if "/" in model_id:
                # skip namespaced ids (openrouter uses vendor/model)
                continue
            alias_key = model_id
            if alias_key in merged:
                continue
            aliased = classify(prov, model_id)
            aliased["display"] = f"{aliased['display']} ({prov})"
            merged[alias_key] = aliased

    # Sort models for stable output (minimax first, then alphabetical).
    sorted_keys = sorted(merged.keys(), key=lambda k: (k.split("/", 1)[0], k))
    models_section = {key: merged[key] for key in sorted_keys}

    return {
        "version": "2.1",
        "currency": "USD",
        "fx_to_brl": 5.20,
        "notes": [
            "Gerado automaticamente por scripts/build_pricing.py a partir de /v1/models.",
            "Precos por 1 milhao de tokens. Cache_read e cache_write separados.",
            "Tiers sao aproximacoes por categoria de modelo (ex: 'gpt-5' = GPT-5 normal).",
            "Para precos exatos, consulte a documentacao do provider.",
            "Aliases sem prefixo (ex: 'claude-sonnet-4-6') sao gerados para modelos",
            "que o Claude Code loga sem namespace. Display mostra provider entre ().",
            "billing_mode=free_tier: custo zero (free tier).",
            "billing_mode=token_plan: seria zero se o modelo estiver no Token Plan.",
            "billing_mode=pay_as_you_go: cobra por token (padrao).",
            "billing_mode=unknown: sem informacao - revisar manualmente.",
        ],
        "models": models_section,
        "fallback": {
            "provider": "unknown",
            "display": "???",
            "input": 1.0,
            "output": 3.0,
            "cache_read": 0.10,
            "cache_write": 1.0,
            "unit": "per_million_tokens",
            "billing_mode": "unknown",
            "notes": "Usado quando o modelo nao esta na tabela. Mostra '?' no display.",
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--out", type=Path, default=Path("pricing.json"))
    args = parser.parse_args(argv)

    pricing = build_pricing(args.host)
    args.out.write_text(
        json.dumps(pricing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.out} with {len(pricing['models'])} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
