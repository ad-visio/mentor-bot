from pathlib import Path

import subprocess

import pytest

from versioning import build_version_banner, detect_short_commit, read_version_file


def test_build_version_banner_formats_values() -> None:
    banner = build_version_banner("1.2.3", "abc123")
    assert banner == "Mentor Bot v1.2.3 (commit abc123)"


def test_read_version_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "VERSION"
    assert read_version_file(path) == "unknown"


def test_read_version_file_present(tmp_path: Path) -> None:
    path = tmp_path / "VERSION"
    path.write_text("1.0.0", encoding="utf-8")
    assert read_version_file(path) == "1.0.0"

    path.write_text("\n1.2.3\n", encoding="utf-8")
    assert read_version_file(path) == "1.2.3"


def test_detect_short_commit_handles_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert detect_short_commit(tmp_path) == "no-git"
