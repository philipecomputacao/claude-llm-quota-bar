"""Parse Claude Code session JSONL logs into aggregated token stats.

Claude Code logs each assistant message to a per-session JSONL file under
``~/.claude/projects/<project-hash>/<session-id>.jsonl``. Each line is a JSON
object that may include ``type`` ("assistant" for model replies), ``message``
containing ``model`` and ``usage`` keys, plus ``sessionId`` and ``timestamp``.

This module reads the file once and aggregates token usage for the requested
session. Designed to be safe to run on every statusline refresh (<50ms target).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class TokenTotals:
    """Aggregated token usage for a session."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    request_count: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    last_model: str | None = None
    last_provider: str | None = None

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    def merge(self, other: TokenTotals) -> TokenTotals:
        """Return a new totals object that sums self and other."""
        first = self.first_timestamp
        if other.first_timestamp and (first is None or other.first_timestamp < first):
            first = other.first_timestamp
        last = self.last_timestamp
        if other.last_timestamp and (last is None or other.last_timestamp > last):
            last = other.last_timestamp
        last_model = other.last_model or self.last_model
        last_provider = other.last_provider or self.last_provider
        return TokenTotals(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens
            + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            request_count=self.request_count + other.request_count,
            first_timestamp=first,
            last_timestamp=last,
            last_model=last_model,
            last_provider=last_provider,
        )


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """Single assistant entry parsed from the JSONL."""

    session_id: str
    timestamp: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int


def _provider_from_model(model_id: str) -> str:
    """Extract provider prefix from a model id.

    Recognises both direct refs (``minimax/MiniMax-M3``) and free-claude-code
    gateway IDs (``anthropic/minimax/MiniMax-M3`` or
    ``claude-3-freecc-no-thinking/minimax/MiniMax-M3``). For gateway IDs the
    ``anthropic/`` / ``claude-3-freecc-no-thinking/`` prefix is stripped first
    so the real upstream provider (``minimax``) is returned, not ``anthropic``.
    """
    stripped = _strip_gateway_prefix(model_id)
    if "/" in stripped:
        return stripped.split("/", 1)[0]
    return "anthropic" if stripped.startswith("claude") else "unknown"


# Gateway ID prefixes used by free-claude-code (fcc-claude). See
# https://github.com/philipecomputacao/free-claude-code-minimax and the
# ``GATEWAY_MODEL_ID_PREFIX`` / ``NO_THINKING_GATEWAY_MODEL_ID_PREFIX``
# constants in fcc-claude's ``api/gateway_model_ids.py``. The statusline is a
# separate project and intentionally does not import from fcc-claude.
_FCC_GATEWAY_PREFIXES: tuple[str, ...] = (
    "anthropic/",
    "claude-3-freecc-no-thinking/",
)


def _strip_gateway_prefix(model_id: str) -> str:
    """Strip the free-claude-code gateway prefix from ``model_id`` if present.

    Direct provider refs (``minimax/MiniMax-M3``) and Anthropic-native ids
    (``claude-3-5-sonnet-...``) pass through unchanged.
    """
    for prefix in _FCC_GATEWAY_PREFIXES:
        if model_id.startswith(prefix):
            return model_id[len(prefix):]
    return model_id


def _parse_assistant(entry: dict) -> AssistantMessage | None:
    """Parse a single JSONL entry into an AssistantMessage, if applicable."""
    if entry.get("type") != "assistant":
        return None
    message = entry.get("message") or {}
    if message.get("role") != "assistant":
        return None
    model = message.get("model")
    if not isinstance(model, str) or not model:
        return None
    usage = message.get("usage") or {}
    return AssistantMessage(
        session_id=entry.get("sessionId", ""),
        timestamp=entry.get("timestamp", ""),
        model=model,
        provider=_provider_from_model(model),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_creation_tokens=int(
            (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0)
        ) + int(
            (usage.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0)
        )
        if isinstance(usage.get("cache_creation"), dict)
        else int(usage.get("cache_creation_input_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
    )


def _empty_totals() -> TokenTotals:
    return TokenTotals()


def aggregate_session(jsonl_path: Path, session_id: str | None) -> TokenTotals:
    """Aggregate token usage from ``jsonl_path`` for the given ``session_id``.

    If ``session_id`` is ``None`` or empty, returns an empty :class:`TokenTotals`.
    If the file does not exist or cannot be read, returns an empty totals too.
    """
    if not session_id:
        return _empty_totals()
    if not jsonl_path.exists():
        return _empty_totals()

    totals = _empty_totals()
    try:
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parsed = _parse_assistant(entry)
                if parsed is None:
                    continue
                if parsed.session_id != session_id:
                    continue
                one = TokenTotals(
                    input_tokens=parsed.input_tokens,
                    output_tokens=parsed.output_tokens,
                    cache_creation_tokens=parsed.cache_creation_tokens,
                    cache_read_tokens=parsed.cache_read_tokens,
                    request_count=1,
                    first_timestamp=parsed.timestamp,
                    last_timestamp=parsed.timestamp,
                    last_model=parsed.model,
                    last_provider=parsed.provider,
                )
                totals = totals.merge(one)
    except OSError:
        return _empty_totals()
    return totals


def _aggregate_lines(lines: Iterable[str], session_id: str) -> TokenTotals:
    """Legacy helper kept for tests; iterates ``lines`` eagerly."""
    totals = _empty_totals()
    for raw in list(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed = _parse_assistant(entry)
        if parsed is None:
            continue
        if parsed.session_id != session_id:
            continue
        one = TokenTotals(
            input_tokens=parsed.input_tokens,
            output_tokens=parsed.output_tokens,
            cache_creation_tokens=parsed.cache_creation_tokens,
            cache_read_tokens=parsed.cache_read_tokens,
            request_count=1,
            first_timestamp=parsed.timestamp,
            last_timestamp=parsed.timestamp,
            last_model=parsed.model,
            last_provider=parsed.provider,
        )
        totals = totals.merge(one)
    return totals


def project_dir_to_hash(project_dir: str) -> str:
    """Convert ``/Users/luiz/Projetos/foo`` to ``-Users-luiz-Projetos-foo``.

    Mirrors Claude Code's ``~/.claude/projects/`` directory naming convention.
    """
    if not project_dir:
        return ""
    return project_dir.replace(os.sep, "-")


def locate_session_log(claude_dir: Path, project_dir: str, session_id: str) -> Path | None:
    """Find the JSONL file for ``session_id`` under the project dir.

    Returns the most recent matching file if multiple exist (defensive — Claude
    Code normally produces one file per session).
    """
    if not project_dir or not session_id:
        return None
    project_hash = project_dir_to_hash(project_dir)
    project_path = claude_dir / "projects" / project_hash
    if not project_path.exists():
        return None
    matches = sorted(project_path.glob(f"{session_id}.jsonl"))
    if matches:
        return matches[-1]
    matches = sorted(project_path.glob(f"*-{session_id}.jsonl"))
    if matches:
        return matches[-1]
    return None


def locate_latest_log(claude_dir: Path, project_dir: str) -> Path | None:
    """Find the most recent JSONL in the project's directory.

    Fallback when session id is not available.
    """
    if not project_dir:
        return None
    project_hash = project_dir_to_hash(project_dir)
    project_path = claude_dir / "projects" / project_hash
    if not project_path.exists():
        return None
    matches = sorted(project_path.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def parse_first_response_model(jsonl_path: Path) -> str | None:
    """Return the model id of the first assistant message, if any.

    Used as a fallback when no session id is provided.
    """
    if not jsonl_path.exists():
        return None
    try:
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                parsed = _parse_assistant(entry)
                if parsed is not None:
                    return parsed.model
    except OSError:
        return None
    return None
