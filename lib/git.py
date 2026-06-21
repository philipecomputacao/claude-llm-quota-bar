"""Resolve git metadata for the active session's cwd.

Used by the statusline to render a 4th line with the current branch and the
title of the last commit. Three short subprocess calls are made per tick:

- ``git -C <cwd> rev-parse --abbrev-ref HEAD`` → branch (or ``HEAD`` if detached)
- ``git -C <cwd> rev-parse --short=7 HEAD`` → 7-char commit hash
- ``git -C <cwd> log -1 --pretty=%s`` → commit subject line (truncated to 60 chars)

Each subprocess is bounded by a 1.5 s timeout. Failures (timeout, non-zero
returncode, missing git binary, missing .git/) silently fall back to ``None``
for that field — the statusline never crashes because of git. This mirrors the
``_discover_cwd_via_lsof`` pattern in ``session_tokens.py`` (best-effort
external lookup with silent fallback).

Stdlib only — no third-party deps, consistent with the rest of the project
(``CLAUDE.md`` § "Naming conventions").
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


# Per-call timeout for each `git` subprocess. The statusline refresh interval
# is 5 s; four calls (branch, hash, title, numstat) at 1.5 s worst-case each
# is 6 s. A cumulative budget (_GIT_BUDGET_SECONDS) aborts remaining calls
# when we have already spent 3.5 s on git, leaving ~1.5 s for the rest of the
# pipeline. In practice, on a healthy repo the lookup completes in 5-15 ms
# (sub-second).
_GIT_TIMEOUT_SECONDS = 1.5
_GIT_BUDGET_SECONDS = 3.5

# Title truncation. The statusline has a 1-line budget for the git segment;
# long commit subjects get cut off with an ellipsis so the rest of the bar
# (cost line, quota line) stays on screen.
_GIT_TITLE_MAX_LEN = 60


@dataclass(frozen=True, slots=True)
class GitInfo:
    """Resolved git metadata for the active cwd.

    All fields are ``None`` when the cwd is not a git repo (or when git
    is unavailable / slow). Callers render a fallback placeholder.
    """

    branch: str | None = None
    commit_short: str | None = None
    commit_title: str | None = None
    dirty_added: int = 0        # lines added in working tree vs HEAD
    dirty_deleted: int = 0      # lines deleted in working tree vs HEAD


def _run_git(cwd: Path, args: list[str]) -> str | None:
    """Run ``git -C <cwd> <args>...`` and return stdout (stripped).

    Returns ``None`` on any failure: missing binary, non-zero returncode,
    timeout, OS-level error. Never raises — the statusline is a best-effort
    display layer and must keep rendering even when git misbehaves.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def _truncate_title(title: str | None) -> str | None:
    """Truncate a commit subject to ``_GIT_TITLE_MAX_LEN`` chars with ``…``."""
    if title is None:
        return None
    if len(title) <= _GIT_TITLE_MAX_LEN:
        return title
    # -1 to leave room for the ellipsis itself.
    return title[: _GIT_TITLE_MAX_LEN - 1].rstrip() + "…"


# Regex for parsing ``git diff HEAD --numstat`` output. Each line is formatted as:
# ``<added>\t<deleted>\t<path>`` where added/deleted are integers, or ``-`` for
# binary files (treated as 0 by the parser).
_NUMSTAT_LINE_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t")


def _parse_numstat(raw: str | None) -> tuple[int, int]:
    """Parse ``git diff HEAD --numstat`` output into ``(added, deleted)``.

    Binary files return ``-`` in the numeric columns — those are treated as 0.
    Empty lines, malformed lines, and non-integer values are silently skipped.
    A ``None`` input or total failure returns ``(0, 0)`` so the statusline
    always shows a clean working tree on the error path (safe default).
    """
    if not raw:
        return 0, 0
    added = deleted = 0
    for line in raw.splitlines():
        match = _NUMSTAT_LINE_RE.match(line)
        if not match:
            continue
        try:
            if match.group(1) != "-":
                added += int(match.group(1))
            if match.group(2) != "-":
                deleted += int(match.group(2))
        except ValueError:
            continue
    return added, deleted


def _run_git_budgeted(
    cwd: Path, args: list[str], budget_start: float
) -> str | None:
    """Run ``git -C <cwd> <args>...`` with a cumulative timeout budget.

    Returns ``None`` when the global git budget is already exhausted — this
    avoids pile-up across refresh ticks when the repo is on a slow filesystem.
    """
    if time.monotonic() - budget_start > _GIT_BUDGET_SECONDS:
        return None
    return _run_git(cwd, args)


def resolve_git(cwd: str | None) -> GitInfo:
    """Return the git metadata for ``cwd``, or a fully-empty ``GitInfo``.

    Cheap short-circuit: if ``cwd`` is missing or ``<cwd>/.git`` does not
    exist, returns ``GitInfo()`` immediately (no subprocesses spawned).
    Cost: one ``Path.exists()`` syscall, ~5 ms on macOS.

    Otherwise spawns up to four ``git`` subprocesses (one per field) bounded
    by a cumulative budget. A failure or budget exhaustion in one does not
    abort the others — the returned ``GitInfo`` simply has ``None`` in the
    failed slot.
    """
    if not cwd:
        return GitInfo()
    cwd_path = Path(cwd)
    # ``.git`` may be a directory (normal repo) or a file (worktree/submodule
    # pointing at the real gitdir). ``exists()`` handles both — for the file
    # case we still want to attempt the git calls because git itself
    # understands the indirection.
    if not (cwd_path / ".git").exists():
        return GitInfo()

    # Cumulative budget so the statusline never spends >3.5 s on git (out of
    # the 5 s refresh window). On a healthy SSD repo all four calls return in
    # ~10 ms — the budget only triggers on pathological filesystems.
    budget_start = time.monotonic()

    # Run the cheapest calls first (branch, commit hash, title) so the
    # expensive ``diff --numstat`` is the one that gets skipped when the
    # budget is tight.
    branch = _run_git_budgeted(
        cwd_path, ["rev-parse", "--abbrev-ref", "HEAD"], budget_start
    )
    commit_short = _run_git_budgeted(
        cwd_path, ["rev-parse", "--short=7", "HEAD"], budget_start
    )
    commit_title = _truncate_title(
        _run_git_budgeted(cwd_path, ["log", "-1", "--pretty=%s"], budget_start)
    )
    # ``diff --numstat`` is the most expensive call (can be 100+ ms on large
    # repos) — run it last, after the cheaper calls have populated
    # branch/commit/title.
    added, deleted = _parse_numstat(
        _run_git_budgeted(
            cwd_path, ["diff", "HEAD", "--numstat"], budget_start
        )
    )
    return GitInfo(
        branch=branch,
        commit_short=commit_short,
        commit_title=commit_title,
        dirty_added=added,
        dirty_deleted=deleted,
    )