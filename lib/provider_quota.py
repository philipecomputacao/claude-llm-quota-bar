"""Provider quota tracking for fcc-claude providers.

Each provider in :data:`config.provider_catalog.PROVIDER_CATALOG` may expose a
quota API. The statusline renders a single ``⏱`` segment per active provider.
Providers without a live quota adapter contribute no segment — the line is
simply absent, not a misleading static placeholder.

Currently wired up:

* ``minimax`` → ``GET https://www.minimax.io/v1/token_plan/remains``
  (5h rolling + weekly windows, see the platform Token Plan docs).
* ``open_router`` → ``GET https://openrouter.ai/api/v1/credits``
  (total credits minus total usage).

All other 16 providers in the fcc-claude catalog have no public quota API at
this time. Add an adapter below and register it in :data:`QUOTA_PROVIDERS`
to enable the segment.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

CACHE_DIRNAME = "claude-code-statusline"
CACHE_FILENAME = "provider-quota.json"

DEFAULT_CACHE_TTL_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 5.0

_FCC_ENV_PATH = Path.home() / ".fcc" / ".env"


@dataclass(frozen=True, slots=True)
class QuotaInfo:
    """Provider-agnostic quota snapshot."""

    provider_id: str
    # ``status_label`` is the short, human-readable badge. Examples:
    # ``"60% livre"``, ``"$8.50 credits"``, ``"free"``, ``"local"``.
    status_label: str
    # ``detail`` is optional extra context that follows the label, e.g. a
    # reset countdown like ``"reset 2h48m"``.
    detail: str | None = None
    # ``used_pct`` drives the line colour (green/yellow/red) when set.
    used_pct: float | None = None
    source: str = "static"  # ``"live"`` | ``"cache"`` | ``"static"`` | ``"error"``
    error: str | None = None
    fetched_at: datetime | None = None


class QuotaProvider(Protocol):
    """Adapter contract — implement one per provider that has a quota API."""

    provider_id: str

    def fetch(
        self,
        api_key: str | None = None,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        cache_path: Path | None = None,
        now: float | None = None,
    ) -> QuotaInfo:
        ...


# ---------------------------------------------------------------------------
# Cache helpers (shared between adapters)
# ---------------------------------------------------------------------------


def cache_dir() -> Path:
    return Path.home() / ".cache" / CACHE_DIRNAME


def _cache_path() -> Path:
    return cache_dir() / CACHE_FILENAME


def _read_cache(path: Path, ttl_seconds: float) -> dict[str, QuotaInfo] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    fetched_at = raw.get("_fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return None
    if time.time() - fetched_at > ttl_seconds:
        return None
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, dict):
        return None
    parsed: dict[str, QuotaInfo] = {}
    for provider_id, entry in entries_raw.items():
        if not isinstance(entry, dict):
            continue
        try:
            parsed[provider_id] = QuotaInfo(
                provider_id=provider_id,
                status_label=str(entry.get("status_label", "?")),
                detail=(
                    str(entry["detail"])
                    if isinstance(entry.get("detail"), str)
                    else None
                ),
                used_pct=(
                    float(entry["used_pct"])
                    if isinstance(entry.get("used_pct"), (int, float))
                    else None
                ),
                source="cache",
                error=None,
                fetched_at=datetime.fromtimestamp(fetched_at, tz=timezone.utc),
            )
        except (TypeError, ValueError):
            continue
    return parsed


def _write_cache(path: Path, entries: dict[str, dict[str, object]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"_fetched_at": time.time(), "entries": entries},
                default=str,
            ),
            encoding="utf-8",
        )
    except OSError:
        # Cache failure is non-fatal; quota tracking still works without cache.
        return


def _request_json(url: str, headers: dict[str, str]) -> tuple[int, dict[str, object] | str]:
    """GET ``url`` with ``headers``; return ``(status, body)`` where body is a
    parsed JSON dict when possible, otherwise the raw text."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        # ``HTTPError`` is also a file-like; read its body to surface auth/quota errors.
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        return exc.code, raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"network error: {type(exc).__name__}: {exc}"
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# MiniMax — live 5h rolling + weekly windows
# ---------------------------------------------------------------------------


_MINIMAX_URL = "https://www.minimax.io/v1/token_plan/remains"
_MINIMAX_KEY_LINE_RE = __import__("re").compile(
    r"""^\s*MINIMAX_API_KEY\s*=\s*["']?([^"'#\r\n]+)["']?""",
    __import__("re").MULTILINE,
)


def _read_minimax_key_from_fcc_env(path: Path = _FCC_ENV_PATH) -> str | None:
    """Read ``MINIMAX_API_KEY`` from the fcc-claude managed ``~/.fcc/.env``."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _MINIMAX_KEY_LINE_RE.search(text)
    if not match:
        return None
    key = match.group(1).strip()
    return key or None


def _parse_minimax_payload(payload: object, preferred_kind: str = "general") -> QuotaInfo:
    """Parse the MiniMax Token Plan response into a :class:`QuotaInfo`."""
    if not isinstance(payload, dict):
        return QuotaInfo(
            provider_id="minimax",
            status_label="error",
            source="error",
            error="payload not object",
        )

    if "base_resp" in payload and isinstance(payload["base_resp"], dict):
        status = payload["base_resp"].get("status_code", 0)
        if status not in (0, None, "0", "success"):
            return QuotaInfo(
                provider_id="minimax",
                status_label="error",
                source="error",
                error=f"upstream status_code={status}",
            )

    entries_raw = payload.get("model_remains")
    if not isinstance(entries_raw, list) or not entries_raw:
        return QuotaInfo(
            provider_id="minimax",
            status_label="error",
            source="error",
            error="no model_remains in payload",
        )

    chosen: dict[str, object] | None = None
    for entry in entries_raw:
        if isinstance(entry, dict) and entry.get("model_name") == preferred_kind:
            chosen = entry
            break
    if chosen is None:
        for entry in entries_raw:
            if isinstance(entry, dict) and entry.get("model_name") in {
                "general",
                "text",
                "chat",
            }:
                chosen = entry
                break
    if chosen is None:
        for entry in entries_raw:
            if isinstance(entry, dict):
                chosen = entry
                break
    if chosen is None:
        return QuotaInfo(
            provider_id="minimax",
            status_label="error",
            source="error",
            error="no usable model_remains entry",
        )

    used = _as_int(chosen.get("current_interval_usage_count"))
    limit = _as_int(chosen.get("current_interval_total_count"))
    remaining_pct = _as_float(chosen.get("current_interval_remaining_percent"))
    reset_at = _parse_epoch_ms(chosen.get("end_time"))
    ms_until_reset = _as_int(chosen.get("remains_time"))

    label, used_pct = _format_minimax_window(remaining_pct, used, limit)
    detail = _format_minimax_detail(ms_until_reset, reset_at)

    return QuotaInfo(
        provider_id="minimax",
        status_label=label,
        detail=detail,
        used_pct=used_pct,
        source="live",
    )


def _format_minimax_window(
    remaining_pct: float | None,
    used: int | None,
    limit: int | None,
) -> tuple[str, float | None]:
    """Return ``(label, used_pct)`` for a MiniMax window."""
    if remaining_pct is not None:
        used_pct = max(0.0, min(100.0, 100.0 - remaining_pct))
        return f"{remaining_pct:.0f}% livre", used_pct
    if used is not None and limit:
        used_pct = float(used) / float(limit) * 100.0
        return f"{used_pct:.0f}% usado", used_pct
    return "?", None


def _format_minimax_detail(
    ms_until_reset: int | None,
    reset_at: datetime | None,
) -> str | None:
    if ms_until_reset and ms_until_reset > 0:
        seconds = int(ms_until_reset / 1000)
        if seconds < 60:
            countdown = f"{seconds}s"
        elif seconds < 3600:
            countdown = f"{seconds // 60}m"
        else:
            hours, rem = divmod(seconds, 3600)
            countdown = f"{hours}h{rem // 60}m"
        return f"reset {countdown}"
    return None


def _parse_epoch_ms(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


class MinimaxQuotaProvider:
    """Live 5h + weekly quota for MiniMax Token Plan."""

    provider_id = "minimax"

    def fetch(
        self,
        api_key: str | None = None,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        cache_path: Path | None = None,
        now: float | None = None,
    ) -> QuotaInfo:
        cache_p = cache_path or _cache_path()
        if not api_key:
            api_key = (
                _read_minimax_key_from_fcc_env()
                or os.environ.get("MINIMAX_API_KEY")
            )
        if not api_key:
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error="MINIMAX_API_KEY not set",
            )

        cached = _read_cache(cache_p, cache_ttl_seconds)
        if cached is not None and self.provider_id in cached:
            return cached[self.provider_id]

        status, body = _request_json(
            _MINIMAX_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        if status != 200:
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error=f"upstream HTTP {status}: {str(body)[:120]}",
            )
        if not isinstance(body, dict):
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error="payload not object",
            )

        info = _parse_minimax_payload(body)
        if info.source == "live":
            _write_cache(
                cache_p,
                {
                    self.provider_id: {
                        "status_label": info.status_label,
                        "detail": info.detail,
                        "used_pct": info.used_pct,
                        "fetched_at": now or time.time(),
                    },
                },
            )
            return QuotaInfo(
                provider_id=info.provider_id,
                status_label=info.status_label,
                detail=info.detail,
                used_pct=info.used_pct,
                source="live",
                fetched_at=datetime.fromtimestamp(now or time.time(), tz=timezone.utc),
            )
        return info


# ---------------------------------------------------------------------------
# OpenRouter — credits remaining
# ---------------------------------------------------------------------------


_OPENROUTER_URL = "https://openrouter.ai/api/v1/credits"


def _read_openrouter_key_from_fcc_env(path: Path = _FCC_ENV_PATH) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    import re

    match = re.search(
        r"""^\s*OPENROUTER_API_KEY\s*=\s*["']?([^"'#\r\n]+)["']?""",
        text,
        re.MULTILINE,
    )
    if not match:
        return None
    key = match.group(1).strip()
    return key or None


def _parse_openrouter_payload(payload: object) -> QuotaInfo:
    """Parse OpenRouter ``GET /api/v1/credits`` response.

    Tolerant of common shapes:

    * ``{"data": {"total_credits": 10, "total_usage": 2.5}}``
    * ``{"total_credits": 10, "total_usage": 2.5}``
    * ``{"data": {"limit": 10, "usage": 2.5}}``
    """
    if not isinstance(payload, dict):
        return QuotaInfo(
            provider_id="open_router",
            status_label="error",
            source="error",
            error="payload not object",
        )

    data: object = payload
    if "data" in payload and isinstance(payload["data"], dict):
        data = payload["data"]
    elif "data" in payload and isinstance(payload["data"], list) and payload["data"]:
        # Some shapes wrap a single dict inside a list.
        first = payload["data"][0]
        if isinstance(first, dict):
            data = first

    if not isinstance(data, dict):
        return QuotaInfo(
            provider_id="open_router",
            status_label="error",
            source="error",
            error="unrecognised credits payload shape",
        )

    total = _as_float(
        data.get("total_credits")
        or data.get("limit")
        or data.get("credit_limit")
        or data.get("balance")
    )
    used = _as_float(
        data.get("total_usage")
        or data.get("usage")
        or data.get("used")
        or data.get("consumed")
    )

    if total is None or used is None:
        return QuotaInfo(
            provider_id="open_router",
            status_label="?",
            source="error",
            error=f"missing credits fields: total={total} used={used}",
        )

    remaining = max(total - used, 0.0)
    used_pct = (used / total * 100.0) if total > 0 else None
    return QuotaInfo(
        provider_id="open_router",
        status_label=f"${remaining:.2f} credits",
        detail=f"${used:.2f} used of ${total:.2f}",
        used_pct=used_pct,
        source="live",
    )


class OpenRouterQuotaProvider:
    """Live credits remaining for OpenRouter."""

    provider_id = "open_router"

    def fetch(
        self,
        api_key: str | None = None,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        cache_path: Path | None = None,
        now: float | None = None,
    ) -> QuotaInfo:
        cache_p = cache_path or _cache_path()
        if not api_key:
            api_key = (
                _read_openrouter_key_from_fcc_env()
                or os.environ.get("OPENROUTER_API_KEY")
            )
        if not api_key:
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error="OPENROUTER_API_KEY not set",
            )

        cached = _read_cache(cache_p, cache_ttl_seconds)
        if cached is not None and self.provider_id in cached:
            return cached[self.provider_id]

        status, body = _request_json(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        if status != 200:
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error=f"upstream HTTP {status}: {str(body)[:120]}",
            )
        if not isinstance(body, dict):
            return QuotaInfo(
                provider_id=self.provider_id,
                status_label="error",
                source="error",
                error="payload not object",
            )

        info = _parse_openrouter_payload(body)
        if info.source == "live":
            _write_cache(
                cache_p,
                {
                    self.provider_id: {
                        "status_label": info.status_label,
                        "detail": info.detail,
                        "used_pct": info.used_pct,
                        "fetched_at": now or time.time(),
                    },
                },
            )
            return QuotaInfo(
                provider_id=info.provider_id,
                status_label=info.status_label,
                detail=info.detail,
                used_pct=info.used_pct,
                source="live",
                fetched_at=datetime.fromtimestamp(now or time.time(), tz=timezone.utc),
            )
        return info


# ---------------------------------------------------------------------------
# Registry — only providers with live quota APIs are listed.
# All other 16 fcc-claude providers return ``None`` from
# :func:`get_quota_for_provider` and the statusline omits the ``⏱`` segment.
# ---------------------------------------------------------------------------


QUOTA_PROVIDERS: dict[str, QuotaProvider] = {
    "minimax": MinimaxQuotaProvider(),
    "open_router": OpenRouterQuotaProvider(),
}


def get_quota_for_provider(provider_id: str | None) -> QuotaProvider | None:
    """Return the live quota adapter for ``provider_id``, or ``None`` if the
    provider has no quota API wired up in this version of the statusline."""
    if not provider_id:
        return None
    return QUOTA_PROVIDERS.get(provider_id)


def fetch_quota(
    provider_id: str | None,
    api_key: str | None = None,
    **kwargs: object,
) -> QuotaInfo | None:
    """Convenience entry: look up the adapter for ``provider_id`` and fetch.

    Returns ``None`` when no adapter exists for the given provider. Callers
    should treat ``None`` as "show nothing for the quota segment".
    """
    adapter = get_quota_for_provider(provider_id)
    if adapter is None:
        return None
    return adapter.fetch(api_key, **kwargs)
