from pathlib import Path

from versioning import build_version_banner, read_version_file


def test_build_version_banner_formats_values() -> None:
    banner = build_version_banner("1.2.3", "abc123", "2024-05-01")
    assert banner == "MentorBot v1.2.3 (abc123, 2024-05-01)"


def test_read_version_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "VERSION"
    assert read_version_file(path) == "unknown"


def test_read_version_file_present(tmp_path: Path) -> None:
    path = tmp_path / "VERSION"
    path.write_text("1.0.0", encoding="utf-8")
    assert read_version_file(path) == "1.0.0"

    path.write_text("\n1.2.3\n", encoding="utf-8")
    assert read_version_file(path) == "1.2.3"
