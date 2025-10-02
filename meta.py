from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
VERSION_PATH = BASE_DIR / "VERSION"


def get_version() -> str:
    try:
        value = VERSION_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("VERSION file is missing; falling back to 'unknown'")
        return "unknown"
    return value or "unknown"


def get_short_sha() -> str:
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


def get_version_line() -> str:
    return f"Mentor Bot v{get_version()} (commit {get_short_sha()})"
