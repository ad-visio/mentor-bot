from datetime import datetime, timezone

from versioning import build_version_banner


def test_build_version_banner_formats_values() -> None:
    started = datetime(2024, 5, 1, 7, 30, tzinfo=timezone.utc)
    banner = build_version_banner("1.2.3", "abc123", started_at=started)
    assert banner == "Mentor Bot v1.2.3 (commit abc123, started 2024-05-01T07:30:00+00:00)"
