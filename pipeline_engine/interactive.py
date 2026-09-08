"""Interactive stdin helpers for report scripts (CLI vs portal worker).

Portal / pipeline workers have no TTY. Scripts that call ``input()`` must
either accept explicit kwargs/CLI flags, or fall back to safe defaults when
``stdin_is_interactive()`` is False.
"""

from __future__ import annotations

import os
import sys
from typing import Optional


def stdin_is_interactive() -> bool:
    """True when a human can answer prompts (local CLI with a TTY)."""
    if os.environ.get("PIPELINE_NON_INTERACTIVE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def safe_input(prompt: str, *, default: str = "") -> str:
    """
    ``input()`` when interactive; otherwise return ``default`` (no EOFError).
    Empty Enter still resolves to ``default``.
    """
    if not stdin_is_interactive():
        return default
    try:
        raw = input(prompt).strip()
    except EOFError:
        return default
    return raw or default


def env_or_none(*keys: str) -> Optional[str]:
    for key in keys:
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None
