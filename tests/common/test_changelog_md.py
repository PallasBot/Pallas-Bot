"""Tests for Keep a Changelog slicing."""

from pallas.core.shared.utils.changelog_md import slice_keep_a_changelog


def test_slice_keep_a_changelog_keeps_preamble_and_recent_versions() -> None:
    raw = """# Changelog

intro

## [Unreleased]

- wip

## [1.2.0] - 2026-01-02

- a

## [1.1.0] - 2026-01-01

- b

## [1.0.0] - 2025-12-01

- c
"""
    out = slice_keep_a_changelog(raw, max_versions=2, changelog_url="https://example.com/CHANGELOG.md")
    assert "intro" in out
    assert "## [Unreleased]" in out
    assert "## [1.2.0]" in out
    assert "## [1.1.0]" not in out
    assert "仅展示最近 2 个版本" in out
    assert "https://example.com/CHANGELOG.md" in out


def test_slice_keep_a_changelog_no_truncate_when_short() -> None:
    raw = "## [1.0.0]\n\n- ok\n"
    out = slice_keep_a_changelog(raw, max_versions=10)
    assert out == "## [1.0.0]\n\n- ok"
    assert "仅展示" not in out
