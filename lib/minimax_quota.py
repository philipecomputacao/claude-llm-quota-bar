"""MiniMax Token Plan quota tracking.

Fetches subscription quota state from ``GET https://www.minimax.io/v1/token_plan/remains``
using the same Subscription Key the statusline's provider config uses
(read from ``~/.fcc/.env`` if the user has configured fcc-claude).

The endpoint returns a ``model_remains`` array — one entry per resource type
(``"general"`` for text/chat, ``"video"`` for video, etc.). Each entry carries
the current 5-hour rolling window state plus the weekly window state. MiniMax's
weekly window has no hard usage cap (the docs describe it as a fairness
guardrail, not a quota), so the weekly ``limit`` is reported as ``None`` when
absent and the statusline simply skips the week segment instead of rendering
a misleading value.

Cached in ``~/.cache/claude-code-statusline/minimax-quota.json`` with a short
TTL (default 60s) so refresh intervals up to ~1 minute don't hit the network.
Errors are swallowed into a sentinel :class:`QuotaInfo` (``source="error"``) so
the statusline keeps working when the upstream quota endpoint is down.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIRNAME = "claude-code-statusline"
CACHE_FILENAME = "minimax-quota.json"

QUOTA_URL = "https://www.minimax.io/v1/token_plan/remains"
DEFAULT_CACHE_TTL_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 5.0

_FCC_ENV_PATH = Path.home() / ".fcc" / ".env"
_MINIMAX_KEY_LINE_RE = re.compile(
    r"""^\s*MINIMAX_API_KEY\s*=\s*["']?([^"'#\r\n]+)["']?""",
    re.MULTILINE,
)

# resource types we know how to surface; anything else is ignored.
# "general" is the text/chat quota most users care about.
_KNOWN_RESOURCE_KINDS: tuple[str, ...] = ("general", "text", "chat")


@dataclass(frozen=True, slots=True)
class WindowQuota:
    """Quota state for a single rolling window (5h or weekly).

    Counts are in MiniMax "quota units" — not literal tokens — and the weekly
    window often has no hard cap (``limit is None``). ``remaining_percent`` is
    what the upstream API returns directly (e.g. ``96`` means 96% left).
    """

    used: int | None = None
    limit: int | None = None
    remaining_percent: float | None = None
    reset_at: datetime | None = None
    ms_until_reset: int | None = None
    status: int | None = None

    @property
    def remaining(self) -> int | None:
        """Remaining quota units; ``None`` when the limit is unknown."""
        if self.used is None or self.limit is None:
            return None
        return max(self.limit - self.used, 0)

    @property
    def used_pct(self) -> float | None:
        if self.used is None or not self.limit:
            return None
        return self.used / self.limit * 100.0

    @property
    def has_limit(self) -> bool:
        return isinstance(self.limit, int) and self.limit > 0


@dataclass(frozen=True, slots=True)
class QuotaInfo:
    """Token Plan quota snapshot for the active subscription key."""

    resource_kind: str | None = None  # e.g. "general"
    five_hour: WindowQuota = field(default_factory=WindowQuota)
    weekly: WindowQuota = field(default_factory=WindowQuota)
    source: str = "unknown"  # "live" | "cache" | "error"
    error: str | None = None
    fetched_at: datetime | None = None


def read_minimax_key_from_fcc_env(path: Path = _FCC_ENV_PATH) -> str | None:
    """Read ``MINIMAX_API_KEY`` from the fcc-claude managed ``~/.fcc/.env``.

    Returns ``None`` if the file or key is absent. Does not raise.
    """
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


def cache_dir() -> Path:
    return Path.home() / ".cache" / CACHE_DIRNAME


def _cache_path() -> Path:
    return cache_dir() / CACHE_FILENAME


def _read_cache(path: Path, ttl_seconds: float) -> QuotaInfo | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    fetched_at_ts = raw.get("_fetched_at")
    if not isinstance(fetched_at_ts, (int, float)):
        return None
    if time.time() - fetched_at_ts > ttl_seconds:
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    info = _parse_payload(payload)
    return QuotaInfo(
        resource_kind=info.resource_kind,
        five_hour=info.five_hour,
        weekly=info.weekly,
        source="cache",
        error=None,
        fetched_at=datetime.fromtimestamp(fetched_at_ts, tz=timezone.utc),
    )


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"_fetched_at": time.time(), "payload": payload}),
            encoding="utf-8",
        )
    except OSError:
        # Cache failure is non-fatal; quota tracking still works without cache.
        return


def _parse_epoch_ms(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _parse_int(value: Any) -> int | None:
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


def _parse_float(value: Any) -> float | None:
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


def _parse_window(
    *,
    usage: int | None,
    total: int | None,
    remaining_percent: float | None,
    reset_at: datetime | None,
    ms_until_reset: int | None,
    status: int | None,
) -> WindowQuota:
    return WindowQuota(
        used=usage,
        limit=total,
        remaining_percent=remaining_percent,
        reset_at=reset_at,
        ms_until_reset=ms_until_reset,
        status=status,
    )


def _parse_entry(entry: dict[str, Any]) -> tuple[WindowQuota, WindowQuota]:
    """Parse one ``model_remains`` entry into (5h, weekly) WindowQuotas."""
    five_h = _parse_window(
        usage=_parse_int(entry.get("current_interval_usage_count")),
        total=_parse_int(entry.get("current_interval_total_count")),
        remaining_percent=_parse_float(entry.get("current_interval_remaining_percent")),
        reset_at=_parse_epoch_ms(entry.get("end_time")),
        ms_until_reset=_parse_int(entry.get("remains_time")),
        status=_parse_int(entry.get("current_interval_status")),
    )
    weekly = _parse_window(
        usage=_parse_int(entry.get("current_weekly_usage_count")),
        total=_parse_int(entry.get("current_weekly_total_count")),
        remaining_percent=_parse_float(entry.get("current_weekly_remaining_percent")),
        reset_at=_parse_epoch_ms(entry.get("weekly_end_time")),
        ms_until_reset=_parse_int(entry.get("weekly_remains_time")),
        status=_parse_int(entry.get("current_weekly_status")),
    )
    return five_h, weekly


def _pick_entry(
    entries: list[dict[str, Any]],
    preferred_kind: str | None,
) -> dict[str, Any] | None:
    """Pick the most relevant ``model_remains`` entry for the active session.

    Preference order:
      1. ``preferred_kind`` (e.g. ``"general"`` when the active model is text)
      2. Any entry whose ``model_name`` is in :data:`_KNOWN_RESOURCE_KINDS`
      3. First entry (best-effort fallback)
    """
    if not entries:
        return None
    if preferred_kind:
        for entry in entries:
            if entry.get("model_name") == preferred_kind:
                return entry
    for kind in _KNOWN_RESOURCE_KINDS:
        for entry in entries:
            if entry.get("model_name") == kind:
                return entry
    return entries[0]


def _parse_payload(payload: dict[str, Any], *, preferred_kind: str = "general") -> QuotaInfo:
    """Parse the upstream quota response into a :class:`QuotaInfo`."""
    if "base_resp" in payload and isinstance(payload["base_resp"], dict):
        status = payload["base_resp"].get("status_code", 0)
        if status not in (0, None, "0", "success"):
            return QuotaInfo(error=f"upstream status_code={status}")

    entries_raw = payload.get("model_remains")
    if not isinstance(entries_raw, list) or not entries_raw:
        return QuotaInfo(error="no model_remains in payload")

    entries: list[dict[str, Any]] = [e for e in entries_raw if isinstance(e, dict)]
    chosen = _pick_entry(entries, preferred_kind)
    if chosen is None:
        return QuotaInfo(error="no usable model_remains entry")

    five_h, weekly = _parse_entry(chosen)
    kind_value = chosen.get("model_name")
    return QuotaInfo(
        resource_kind=kind_value if isinstance(kind_value, str) else None,
        five_hour=five_h,
        weekly=weekly,
    )


def fetch_minimax_quota(
    api_key: str | None = None,
    *,
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    cache_path: Path | None = None,
    now: float | None = None,
    preferred_kind: str = "general",
) -> QuotaInfo:
    """Fetch the current MiniMax Token Plan quota.

    Caches the most recent successful response in
    ``~/.cache/claude-code-statusline/minimax-quota.json`` for
    ``cache_ttl_seconds``. Returns the cached value when fresh and the live
    call is unavailable.

    A ``None`` or empty ``api_key`` resolves the key from ``~/.fcc/.env`` or
    the ``MINIMAX_API_KEY`` env var. Network and parse errors produce a
    :class:`QuotaInfo` with ``source="error"`` and ``error`` set, so callers
    can render nothing rather than breaking the statusline.
    """
    cache_p = cache_path or _cache_path()

    if not api_key:
        api_key = read_minimax_key_from_fcc_env() or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return QuotaInfo(source="error", error="MINIMAX_API_KEY not set")

    cached = _read_cache(cache_p, cache_ttl_seconds)
    if cached is not None:
        return cached

    request = urllib.request.Request(
        QUOTA_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return QuotaInfo(source="error", error=f"upstream {type(exc).__name__}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return QuotaInfo(source="error", error=f"parse {type(exc).__name__}")
    if not isinstance(payload, dict):
        return QuotaInfo(source="error", error="payload not object")

    info = _parse_payload(payload, preferred_kind=preferred_kind)
    if info.error is None:
        _write_cache(cache_p, payload)
        return QuotaInfo(
            resource_kind=info.resource_kind,
            five_hour=info.five_hour,
            weekly=info.weekly,
            source="live",
            error=None,
            fetched_at=datetime.fromtimestamp(now or time.time(), tz=timezone.utc),
        )
    return QuotaInfo(source="error", error=info.error)
