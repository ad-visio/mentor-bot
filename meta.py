from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

BASE_DIR: Final = Path(__file__).resolve().parent
VERSION_PATH: Final = BASE_DIR / "VERSION"

_VERSION: str | None = None
_SHORT_SHA: str | None = None
_VERSION_LINE: str | None = None


def _read_version() -> str:
    try:
        value = VERSION_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("VERSION file is missing; falling back to 'unknown'")
        return "unknown"
    return value or "unknown"


def _read_short_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return "unknown"

    if result.returncode != 0:
        return "unknown"

    short_sha = result.stdout.strip()
    return short_sha or "unknown"


def get_version() -> str:
    global _VERSION
    if _VERSION is None:
        _VERSION = _read_version()
    return _VERSION


def get_short_sha() -> str:
    global _SHORT_SHA
    if _SHORT_SHA is None:
        _SHORT_SHA = _read_short_sha()
    return _SHORT_SHA


def get_version_line() -> str:
    global _VERSION_LINE
    if _VERSION_LINE is None:
        _VERSION_LINE = f"Mentor Bot v{get_version()} (commit {get_short_sha()})"
    return _VERSION_LINE


def _reset_cache_for_tests() -> None:
    """Clear cached metadata (used by unit tests)."""

    global _VERSION, _SHORT_SHA, _VERSION_LINE
    _VERSION = None
    _SHORT_SHA = None
    _VERSION_LINE = None
