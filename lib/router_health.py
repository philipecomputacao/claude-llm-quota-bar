"""Lightweight health check for the local Anthropic proxy (fcc-server).

The statusline renders a 🌐 segment on the cost line that shows whether the
active session is going through a local proxy. The env var tells us *that*
the proxy is configured; this module tells us *whether it's actually alive*.

Without this, the bar happily shows "🌐 http://localhost:<port>" in green
even when fcc-server has crashed — misleading. With this, a dead router
flips to red so the user can tell at a glance that the proxy is down.

The check is intentionally cheap:

- Stdlib only (``urllib.request`` — no ``requests``, no ``httpx``).
- Single HEAD request to the root path (``/``) of the proxy URL. Proxies
  in the fcc-claude ecosystem return 404/405 on HEAD to ``/``, which is
  still a valid "server is alive" signal. A TCP RST / connection refused
  is the "dead" signal.
- 1.0s timeout — long enough to absorb a slow TCP handshake, short enough
  to keep the statusline responsive.
- 45s cache TTL — at the default 5s refresh tick, the user sees at most
  one stale health verdict between checks. The trade-off: faster recovery
  (lower TTL) means more requests and more chance of false negatives on
  a momentarily-busy proxy; 45s sits in the sweet spot.
- Single in-flight check per URL — if a tick arrives while a previous
  health check is still pending, we reuse the previous verdict (even if
  stale) instead of stacking requests.

Public API:

- :func:`check_router` — returns ``"ok"``, ``"down"`` or ``"unknown"``
  for the given URL. Reads/writes the module-level cache.

Why a HEAD to ``/``? Two reasons:

1. ``/`` is the cheapest path on most HTTP servers (no auth, no body).
2. We don't want to hit ``/v1/models`` because some proxies (and
   certainly the official Anthropic API) reject unauthenticated
   ``/v1/models`` with 401, which would falsely flag the upstream as
   "down" when it's actually fine. A 404/405 on ``/`` is unambiguous
   "server is up, doesn't serve the root path".

Failure modes (all treated as ``"down"``, never crash):

- DNS resolution fails → ``URLError`` → ``"down"``.
- Connection refused → ``URLError`` (subclass ``ConnectionRefusedError``)
  → ``"down"``.
- Timeout (1.0s) → ``socket.timeout`` → ``"down"``.
- HTTP server returns 5xx → still "ok" (the server responded; the
  user can debug the 5xx separately).
- Any other exception → ``"unknown"`` so the renderer can fall back to
  the default green/grey instead of false-flagging a healthy proxy.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from typing import Literal

#: TTL for the in-memory cache. 45s ≈ 9 ticks at 5s refresh — fast enough
#: to recover from a real crash within ~1 minute, slow enough to avoid
#: hammering the proxy on a busy tick. Override via statusline.env.json
#: (``router_health_ttl_seconds``).
DEFAULT_TTL_SECONDS = 45.0

#: HTTP timeout for the HEAD request. 1.0s is long enough to absorb a
#: normal TCP handshake + TLS (when relevant) on localhost, short enough
#: that a frozen proxy doesn't blank the statusline for more than one
#: tick. Cannot be tuned at runtime — 1.0s is the project-wide contract.
_REQUEST_TIMEOUT_SECONDS = 1.0

RouterHealth = Literal["ok", "down", "unknown"]

# Module-level cache. Keyed by URL so a future change to multi-router
# doesn't require a redesign. ``_lock`` serialises the first-miss path
# so two ticks can't both fire a HEAD for the same URL on the same
# instant. Reads after the first entry is populated are lock-free.
_health_cache: dict[str, tuple[float, RouterHealth]] = {}
_lock = threading.Lock()


def check_router(url: str, *, cache_ttl_seconds: float = DEFAULT_TTL_SECONDS) -> RouterHealth:
    """Return the cached health verdict for ``url``, or probe it if stale.

    The function never raises. All exceptions during the probe are caught
    and converted to a verdict so the statusline keeps rendering.

    Concurrency: a module-level lock protects the cache-miss path so
    parallel ticks don't fire redundant HEADs. Cache hits are
    lock-free (we read the dict, accept that the value may flip between
    the read and the verdict — the worst case is one extra probe).
    """
    now = time.monotonic()
    cached = _health_cache.get(url)
    if cached is not None:
        ts, verdict = cached
        if (now - ts) < cache_ttl_seconds:
            return verdict

    # Cache miss (or expired). Acquire the lock to deduplicate concurrent
    # probes — at most one HEAD per URL per ``cache_ttl_seconds`` window,
    # even under bursty refresh ticks.
    with _lock:
        # Re-check under the lock: another thread may have just probed
        # the same URL while we were waiting.
        cached = _health_cache.get(url)
        if cached is not None:
            ts, verdict = cached
            if (now - ts) < cache_ttl_seconds:
                return verdict
        verdict = _probe(url)
        _health_cache[url] = (time.monotonic(), verdict)
        return verdict


def _probe(url: str) -> RouterHealth:
    """Issue a single HEAD request to ``url`` and translate the result.

    Returns:

    - ``"ok"`` when the server responded (any 2xx/3xx/4xx/5xx — the fact
      that it answered means the listener is up). 5xx is a "server is
      alive but unhappy" state, not a connectivity problem; the user
      can debug that separately and we should not false-flag a proxy
      that the launcher hasn't yet registered as dead.
    - ``"down"`` when the request failed with a network-level error
      (DNS, refused, timeout, reset). These all mean "the listener is
      not accepting connections right now".
    - ``"unknown"`` when an unexpected exception surfaced (e.g. an
      SSL error on a misconfigured proxy). The renderer treats this as
      "render the default colour, don't alarm the user".

    Never raises.
    """
    request = urllib.request.Request(url, method="HEAD")
    try:
        # ``urlopen`` blocks up to ``_REQUEST_TIMEOUT_SECONDS`` total
        # (connect + read). We deliberately don't read the body — HEAD
        # doesn't have one, and even an erroneous 4xx response shouldn't
        # pull payload bytes.
        urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS)
    except urllib.error.HTTPError:
        # The server answered with a non-2xx status. That's still a
        # live listener — 404 on ``/`` is the typical response for a
        # reverse proxy that only forwards specific paths.
        return "ok"
    except urllib.error.URLError:
        # DNS failure, connection refused, TLS error, etc. The listener
        # is not accepting connections — treat as down.
        return "down"
    except (TimeoutError, OSError):
        # ``urlopen`` raises ``socket.timeout`` (which is a subclass of
        # ``OSError``) on a slow response. Catching it explicitly here
        # makes the intent obvious to future readers, even though the
        # ``OSError`` arm below would also catch it.
        return "down"
    except Exception:
        # Anything we didn't anticipate (SSL misconfiguration, locale
        # issues, etc.). Don't crash the statusline — return ``"unknown"``
        # so the renderer falls back to the default colour.
        return "unknown"
    return "ok"
