"""Bot release 更新判定：开发超前 commit 不应提示有更新。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from packages.pb_webui import manager
from packages.pb_webui.manager import (
    bot_branch_update_probe,
    bot_has_release_update,
    bot_is_development_build,
    is_bot_release_style_tag,
    normalize_bot_update_track,
    resolve_bot_upstream_ref,
    webui_has_release_update,
)


def test_normalize_bot_update_track() -> None:
    assert normalize_bot_update_track("branch") == "branch"
    assert normalize_bot_update_track("BRANCH") == "branch"
    assert normalize_bot_update_track("release") == "release"
    assert normalize_bot_update_track("") == "release"
    assert normalize_bot_update_track(None) == "release"


def test_same_tag_no_update() -> None:
    assert not bot_has_release_update(latest_tag="v1.0.0", current_tag="v1.0.0")


def test_no_latest_tag() -> None:
    assert not bot_has_release_update(latest_tag="", current_tag="v0.9.0")


@pytest.mark.parametrize(
    ("head_sha", "latest_sha", "ahead_count", "behind_count", "expected"),
    [
        ("aaa", "aaa", 0, 0, False),
        ("bbb", "aaa", 3, 0, False),  # 纯超前：开发构建
        ("aaa", "bbb", 0, 2, True),  # 纯落后：可升级
        ("ccc", "bbb", 190, 5, False),  # 分叉：不误报「有更新」
    ],
)
def test_git_behind_only(
    head_sha: str,
    latest_sha: str,
    ahead_count: int,
    behind_count: int,
    expected: bool,
) -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[2]
            if ref == "HEAD":
                return head_sha + "\n"
            if ref.endswith("^{commit}"):
                return latest_sha + "\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            r = cmd[3]
            if r == f"{latest_sha}..{head_sha}":
                return f"{ahead_count}\n"
            if r == f"{head_sha}..{latest_sha}":
                return f"{behind_count}\n"
        raise AssertionError(cmd)

    with (
        patch.object(Path, "exists", return_value=True),
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert bot_has_release_update(latest_tag="v1.1.0", current_tag="v1.0.0-dev") is expected


def test_webui_update_ignores_npm_version() -> None:
    assert is_bot_release_style_tag("v3.9.3")
    assert not is_bot_release_style_tag("0.6.35")
    assert not webui_has_release_update(latest_tag="v3.9.3", current_tag="0.6.35")
    assert webui_has_release_update(latest_tag="v3.9.3", current_tag="v3.9.0")
    assert not webui_has_release_update(latest_tag="v3.9.3", current_tag="v3.9.3")


@pytest.mark.parametrize(
    "manifest",
    [
        {},
        {"schema_version": 2, "requires": {"bot": {"min_commit": "a" * 40}}},
        {"schema_version": 1},
        {"schema_version": 1, "requires": {"bot": {}}},
        {"schema_version": 1, "requires": {"bot": {"min_commit": "a" * 39}}},
        {"schema_version": 1, "requires": {"bot": {"min_commit": "A" * 40}}},
    ],
)
def test_webui_release_manifest_requires_supported_bot_baseline(manifest: dict) -> None:
    with pytest.raises(ValueError, match="manifest"):
        manager.parse_webui_release_manifest(manifest)


def test_webui_release_manifest_accepts_supported_bot_baseline() -> None:
    minimum = "a" * 40

    parsed = manager.parse_webui_release_manifest({
        "schema_version": 1,
        "requires": {"bot": {"min_commit": minimum}},
    })

    assert parsed == {"schema_version": 1, "min_bot_commit": minimum}


@pytest.mark.asyncio
async def test_resolve_compatible_webui_release_selects_newest_compatible_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_commit = "f" * 40
    compatible_minimum = "a" * 40
    incompatible_minimum = "b" * 40

    def release(tag: str, suffix: str, *, prerelease: bool = False, manifest: bool = True) -> dict:
        assets = [{"name": "dist.zip", "url": f"https://example.test/{suffix}/dist.zip"}]
        if manifest:
            assets.append({"name": "release-manifest.json", "url": f"https://example.test/{suffix}/manifest"})
        return {
            "tag": tag,
            "html_url": f"https://example.test/releases/{tag}",
            "body": f"notes {tag}",
            "prerelease": prerelease,
            "assets": assets,
        }

    releases = [
        release("v0.9.16", "new", manifest=True),
        release("v0.9.15-dev.1", "preview", prerelease=True),
        release("v0.9.14", "without-manifest", manifest=False),
        release("v0.9.13", "compatible", manifest=True),
    ]
    manifests = {
        "https://example.test/new/manifest": {
            "schema_version": 1,
            "requires": {"bot": {"min_commit": incompatible_minimum}},
        },
        "https://example.test/compatible/manifest": {
            "schema_version": 1,
            "requires": {"bot": {"min_commit": compatible_minimum}},
        },
    }

    async def fetch_manifest(url: str, *, token: str = "") -> dict:
        return manifests[url]

    async def fetch_releases(*_args, **_kwargs) -> list[dict]:
        return releases

    monkeypatch.setattr(manager, "_fetch_webui_release_list", fetch_releases)
    monkeypatch.setattr(manager, "_fetch_webui_release_manifest", fetch_manifest)
    monkeypatch.setattr(manager, "get_bot_current_commit", lambda: bot_commit)
    monkeypatch.setattr(
        manager,
        "is_bot_commit_ancestor",
        lambda minimum, current: minimum == compatible_minimum and current == bot_commit,
    )

    selected = await manager.resolve_compatible_webui_release(
        "PallasBot/Pallas-Bot-WebUI",
        "dist.zip",
    )

    assert selected["tag"] == "v0.9.13"
    assert selected["asset_url"] == "https://example.test/compatible/dist.zip"
    assert "/releases/latest/" not in selected["asset_url"]
    assert selected["min_bot_commit"] == compatible_minimum


@pytest.mark.asyncio
async def test_resolve_pinned_webui_release_does_not_fallback_to_another_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_commit = "f" * 40
    releases = [
        {
            "tag": "v0.9.16",
            "html_url": "https://example.test/releases/v0.9.16",
            "body": "",
            "prerelease": False,
            "assets": [
                {"name": "dist.zip", "url": "https://example.test/v0.9.16/dist.zip"},
                {"name": "release-manifest.json", "url": "https://example.test/v0.9.16/manifest"},
            ],
        },
        {
            "tag": "v0.9.13",
            "html_url": "https://example.test/releases/v0.9.13",
            "body": "",
            "prerelease": False,
            "assets": [
                {"name": "dist.zip", "url": "https://example.test/v0.9.13/dist.zip"},
                {"name": "release-manifest.json", "url": "https://example.test/v0.9.13/manifest"},
            ],
        },
    ]

    async def fetch_manifest(_url: str, *, token: str = "") -> dict:
        return {
            "schema_version": 1,
            "requires": {"bot": {"min_commit": "b" * 40}},
        }

    async def fetch_releases(*_args, **_kwargs) -> list[dict]:
        return releases

    monkeypatch.setattr(manager, "_fetch_webui_release_list", fetch_releases)
    monkeypatch.setattr(manager, "_fetch_webui_release_manifest", fetch_manifest)
    monkeypatch.setattr(manager, "get_bot_current_commit", lambda: bot_commit)
    monkeypatch.setattr(manager, "is_bot_commit_ancestor", lambda *_args: False)

    with pytest.raises(manager.WebuiReleaseCompatibilityError, match="v0.9.16"):
        await manager.resolve_compatible_webui_release(
            "PallasBot/Pallas-Bot-WebUI",
            "dist.zip",
            "v0.9.16",
        )


@pytest.mark.asyncio
async def test_resolve_webui_release_requires_full_bot_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager, "get_bot_current_commit", lambda: "")

    with pytest.raises(manager.WebuiReleaseCompatibilityError, match="完整 commit"):
        await manager.resolve_compatible_webui_release(
            "PallasBot/Pallas-Bot-WebUI",
            "dist.zip",
        )


@pytest.mark.asyncio
async def test_resolve_webui_release_asset_urls_are_strictly_bound_to_selected_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = {
        "tag": "v0.9.13",
        "asset_url": "https://example.test/releases/download/v0.9.13/dist.zip",
    }
    monkeypatch.setattr(manager, "resolve_compatible_webui_release", AsyncMock(return_value=selected))
    urls = await manager.resolve_webui_release_asset_urls(
        "PallasBot/Pallas-Bot-WebUI",
        "dist.zip",
        "v0.9.13",
    )

    assert urls == [selected["asset_url"]]
    assert all("/releases/latest" not in url for url in urls)


def test_get_bot_current_commit_uses_build_provenance_when_git_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    monkeypatch.setattr(manager, "_git_rev_parse_text", lambda *_args: None)
    monkeypatch.setenv("PALLAS_BOT_COMMIT", commit)

    assert manager.get_bot_current_commit() == commit


@pytest.mark.asyncio
async def test_resolve_compatible_webui_release_uses_compare_for_shallow_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_commit = "f" * 40
    minimum = "a" * 40
    release = {
        "tag": "v0.9.13",
        "html_url": "https://example.test/releases/v0.9.13",
        "body": "",
        "prerelease": False,
        "draft": False,
        "assets": [
            {"name": "dist.zip", "url": "https://example.test/v0.9.13/dist.zip"},
            {"name": "release-manifest.json", "url": "https://example.test/v0.9.13/manifest"},
        ],
    }

    async def fetch_releases(*_args, **_kwargs) -> list[dict]:
        return [release]

    async def fetch_manifest(_url: str, *, token: str = "") -> dict:
        return {"schema_version": 1, "requires": {"bot": {"min_commit": minimum}}}

    compare = AsyncMock(return_value="ahead")
    monkeypatch.setattr(manager, "_fetch_webui_release_list", fetch_releases)
    monkeypatch.setattr(manager, "_fetch_webui_release_manifest", fetch_manifest)
    monkeypatch.setattr(manager, "is_bot_commit_ancestor", lambda *_args: False)
    monkeypatch.setattr(manager, "_git_repository_is_shallow", lambda: True, raising=False)
    monkeypatch.setattr(manager, "_fetch_bot_commit_compare_status", compare, raising=False)

    selected = await manager.resolve_compatible_webui_release(
        "PallasBot/Pallas-Bot-WebUI",
        current_commit=bot_commit,
        token="token",
    )

    assert selected["tag"] == "v0.9.13"
    compare.assert_awaited_once_with(minimum, bot_commit, token="token")


@pytest.mark.asyncio
async def test_resolve_compatible_webui_release_skips_draft_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_commit = "f" * 40
    minimum = "a" * 40

    def release(tag: str, suffix: str, *, draft: bool) -> dict:
        return {
            "tag": tag,
            "html_url": f"https://example.test/releases/{tag}",
            "body": "",
            "prerelease": False,
            "draft": draft,
            "assets": [
                {"name": "dist.zip", "url": f"https://example.test/{suffix}/dist.zip"},
                {"name": "release-manifest.json", "url": f"https://example.test/{suffix}/manifest"},
            ],
        }

    releases = [
        release("v0.9.14", "draft", draft=True),
        release("v0.9.13", "published", draft=False),
    ]

    async def fetch_releases(*_args, **_kwargs) -> list[dict]:
        return releases

    async def fetch_manifest(_url: str, *, token: str = "") -> dict:
        return {"schema_version": 1, "requires": {"bot": {"min_commit": minimum}}}

    monkeypatch.setattr(manager, "_fetch_webui_release_list", fetch_releases)
    monkeypatch.setattr(manager, "_fetch_webui_release_manifest", fetch_manifest)
    monkeypatch.setattr(manager, "is_bot_commit_ancestor", lambda *_args: True)

    selected = await manager.resolve_compatible_webui_release(
        "PallasBot/Pallas-Bot-WebUI",
        current_commit=bot_commit,
    )

    assert selected["tag"] == "v0.9.13"


@pytest.mark.asyncio
async def test_validate_webui_dist_archive_checks_manifest_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_commit = "f" * 40
    minimum = "a" * 40
    archive = tmp_path / "dist.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "public-react/release-manifest.json",
            json.dumps({"schema_version": 1, "requires": {"bot": {"min_commit": minimum}}}),
        )

    compatible = AsyncMock(return_value=True)
    monkeypatch.setattr(manager, "is_bot_commit_compatible", compatible, raising=False)

    result = await manager.validate_webui_dist_archive(
        archive,
        token="token",
        current_commit=bot_commit,
    )

    assert result["min_bot_commit"] == minimum
    compatible.assert_awaited_once_with(minimum, bot_commit, token="token")


def test_bot_branch_update_probe_behind() -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"] and cmd[3] == "@{u}":
            return "origin/dev\n"
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[-1]
            if ref == "HEAD":
                return "aaa111\n"
            if ref == "origin/dev":
                return "bbb222ccccdddd\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            if cmd[3] == "aaa111..bbb222ccccdddd":
                return "2\n"
            return "0\n"
        raise AssertionError(cmd)

    with (
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert resolve_bot_upstream_ref() == "origin/dev"
        probe = bot_branch_update_probe()
    assert probe["has_update"] is True
    assert probe["commits_behind"] == 2
    assert probe["latest_commit"] == "bbb222ccccdd"
    assert probe["upstream_ref"] == "origin/dev"


def test_bot_branch_update_probe_preferred_branch() -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:4] == ["git", "rev-parse", "-q", "--verify"] and cmd[4] == "origin/main":
            return "origin/main\n"
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[-1]
            if ref == "HEAD":
                return "aaa111\n"
            if ref == "origin/main":
                return "aaa111\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return "0\n"
        raise AssertionError(cmd)

    with (
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        probe = bot_branch_update_probe(preferred_branch="main")
    assert probe["has_update"] is False
    assert probe["upstream_ref"] == "origin/main"


@pytest.mark.parametrize(
    ("head_sha", "latest_sha", "ahead_count", "expected"),
    [
        ("bbb", "aaa", 3, True),
        ("aaa", "bbb", 0, False),
        ("aaa", "aaa", 0, False),
    ],
)
def test_development_build_ahead(
    head_sha: str,
    latest_sha: str,
    ahead_count: int,
    expected: bool,
) -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[2]
            if ref == "HEAD":
                return head_sha + "\n"
            if ref.endswith("^{commit}"):
                return latest_sha + "\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            r = cmd[3]
            if r == f"{head_sha}..{latest_sha}":
                return "0\n"
            if r == f"{latest_sha}..{head_sha}":
                return f"{ahead_count}\n"
        raise AssertionError(cmd)

    with (
        patch.object(Path, "exists", return_value=True),
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert bot_is_development_build(latest_tag="v1.0.0", current_tag="", current_commit="abc1234") is expected
