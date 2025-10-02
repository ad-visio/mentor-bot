from __future__ import annotations

import logging
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


def read_version_file(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("VERSION file is missing; falling back to 'unknown'")
        return "unknown"
    return value or "unknown"


def detect_short_commit(repo_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return "unknown"
    sha = result.stdout.strip()
    return sha or "unknown"


def detect_commit_date(repo_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%cs", "HEAD"],
            cwd=repo_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return "unknown"
    commit_date = result.stdout.strip()
    return commit_date or "unknown"


def build_version_banner(version: str, commit: str, commit_date: str) -> str:
    return f"MentorBot v{version} ({commit}, {commit_date})"


def load_version_banner(base_dir: Path) -> str:
    version = read_version_file(base_dir / "VERSION")
    commit = detect_short_commit(base_dir)
    commit_date = detect_commit_date(base_dir)
    return build_version_banner(version, commit, commit_date)
