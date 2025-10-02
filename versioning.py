from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def read_version_file(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"
    return value or "0.0.0"


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


def build_version_banner(
    version: str,
    commit: str,
    started_at: datetime | None = None,
) -> str:
    ts = started_at
    if ts is None:
        ts = datetime.now(tz=timezone.utc)
    elif ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return f"Mentor Bot v{version} (commit {commit}, started {ts.isoformat()})"


def load_version_banner(base_dir: Path, started_at: datetime | None = None) -> str:
    version = read_version_file(base_dir / "VERSION")
    commit = detect_short_commit(base_dir)
    return build_version_banner(version, commit, started_at)
