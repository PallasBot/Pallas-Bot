"""Tests for aggregate_release_notes / clean_release_notes_body."""

from __future__ import annotations

from pallas.core.shared.utils.github_release import (
    aggregate_release_notes,
    clean_release_notes_body,
)


def test_clean_release_notes_body_strips_type_footer() -> None:
    raw = "## 更新内容\n\n* feat: x\n\n> **类型**：合并到 main 的 PR\n"
    cleaned = clean_release_notes_body(raw)
    assert "类型" not in cleaned
    assert "feat: x" in cleaned


def test_aggregate_range_current_to_latest() -> None:
    releases = [
        {"tag": "v0.6.39", "body": "notes 39", "prerelease": False},
        {"tag": "v0.6.38", "body": "notes 38", "prerelease": False},
        {"tag": "v0.6.37", "body": "notes 37", "prerelease": False},
        {"tag": "v0.6.36", "body": "notes 36", "prerelease": False},
    ]
    text = aggregate_release_notes(
        releases,
        current_tag="v0.6.37",
        latest_tag="v0.6.39",
        changelog_url="https://example.com/CHANGELOG.md",
        releases_url="https://example.com/releases",
    )
    assert "## v0.6.39" in text
    assert "## v0.6.38" in text
    assert "notes 39" in text
    assert "notes 38" in text
    assert "v0.6.37" not in text
    assert "v0.6.36" not in text


def test_aggregate_up_to_date_falls_back_to_latest() -> None:
    releases = [
        {"tag": "v1.0.0", "body": "only latest", "prerelease": False},
        {"tag": "v0.9.0", "body": "old", "prerelease": False},
    ]
    text = aggregate_release_notes(
        releases,
        current_tag="v1.0.0",
        latest_tag="v1.0.0",
    )
    assert "## v1.0.0" in text
    assert "only latest" in text
    assert "v0.9.0" not in text


def test_aggregate_skips_prerelease_unless_latest() -> None:
    releases = [
        {"tag": "v1.1.0-rc.1", "body": "rc", "prerelease": True},
        {"tag": "v1.0.1", "body": "patch", "prerelease": False},
        {"tag": "v1.0.0", "body": "base", "prerelease": False},
    ]
    text = aggregate_release_notes(
        releases,
        current_tag="v1.0.0",
        latest_tag="v1.0.1",
    )
    assert "v1.1.0-rc.1" not in text
    assert "## v1.0.1" in text
    assert "v1.0.0" not in text


def test_aggregate_max_releases_truncation_footer() -> None:
    releases = [{"tag": f"v0.{i}.0", "body": f"body {i}", "prerelease": False} for i in range(20, 0, -1)]
    text = aggregate_release_notes(
        releases,
        current_tag="v0.1.0",
        latest_tag="v0.20.0",
        max_releases=3,
        changelog_url="https://example.com/CHANGELOG.md",
        releases_url="https://example.com/releases",
    )
    assert "## v0.20.0" in text
    assert "## v0.19.0" in text
    assert "## v0.18.0" in text
    assert "v0.17.0" not in text
    assert "CHANGELOG.md" in text
    assert "最近若干版本" in text


def test_aggregate_notes_max_truncation() -> None:
    long_body = "x" * 5000
    releases = [
        {"tag": "v2.0.0", "body": long_body, "prerelease": False},
        {"tag": "v1.0.0", "body": long_body, "prerelease": False},
    ]
    text = aggregate_release_notes(
        releases,
        current_tag="v1.0.0",
        latest_tag="v2.0.0",
        notes_max=800,
        releases_url="https://example.com/releases",
    )
    assert len(text) < 1200
    assert "已截断" in text
