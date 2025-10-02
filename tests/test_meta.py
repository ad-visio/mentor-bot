from pathlib import Path

import subprocess

import pytest

import meta


@pytest.fixture(autouse=True)
def reset_meta_cache():
    meta._reset_cache_for_tests()
    yield
    meta._reset_cache_for_tests()


def test_get_version_line_formats_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta, "get_version", lambda: "1.2.3")
    monkeypatch.setattr(meta, "get_short_sha", lambda: "abc123")
    assert meta.get_version_line() == "Mentor Bot v1.2.3 (commit abc123)"


def test_get_version_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    version_path = tmp_path / "VERSION"
    monkeypatch.setattr(meta, "VERSION_PATH", version_path)
    assert meta.get_version() == "unknown"


def test_get_version_file_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    version_path = tmp_path / "VERSION"
    version_path.write_text("1.0.0", encoding="utf-8")
    monkeypatch.setattr(meta, "VERSION_PATH", version_path)
    assert meta.get_version() == "1.0.0"


def test_get_version_trims_whitespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    version_path = tmp_path / "VERSION"
    version_path.write_text("\n1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(meta, "VERSION_PATH", version_path)
    assert meta.get_version() == "1.2.3"


def test_get_short_sha_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert meta.get_short_sha() == "unknown"


def test_get_short_sha_handles_non_zero_return(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())
    assert meta.get_short_sha() == "unknown"
