from __future__ import annotations

import subprocess

import pytest

from pallas.console.webui import plugin_update_snapshot as snapshot


@pytest.mark.asyncio
async def test_remote_head_selects_clone_branch_before_same_named_tag(monkeypatch):
    calls = []

    async def fake_git(_timeout, *args, **kwargs):
        calls.append(args)
        return (
            0,
            """a1\trefs/heads/release
b2\trefs/tags/release
c3\trefs/tags/release^{}
d4\trefs/heads/release-next
""",
            "",
        )

    monkeypatch.setattr("pallas.console.webui.community_plugin_install.run_git_command", fake_git)

    assert await snapshot._community_remote_head("repo", "release") == "a1"
    assert calls[0][2:] == ("refs/heads/release", "refs/tags/release^{}", "refs/tags/release")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ref", "output", "expected"),
    [
        ("refs/heads/release", "a1\trefs/heads/release\nb2\trefs/tags/release\n", "a1"),
        ("refs/tags/release", "a1\trefs/tags/release\nb2\trefs/tags/release^{}\n", "b2"),
        ("release", "a1\trefs/tags/release\nb2\trefs/tags/release^{}\n", "b2"),
        ("missing", "a1\trefs/heads/missing-extra\n", None),
        ("release", "", None),
    ],
)
async def test_remote_head_matches_exact_ref_and_peeled_tag(monkeypatch, ref, output, expected):
    async def fake_git(_timeout, *args, **kwargs):
        return 0, output, ""

    monkeypatch.setattr("pallas.console.webui.community_plugin_install.run_git_command", fake_git)

    assert await snapshot._community_remote_head("repo", ref) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("remote", "expected"), [("abc", False), ("def", True), (None, None)])
async def test_check_community_reports_local_remote_commit_comparison(monkeypatch, remote, expected):
    async def local(_plugin_id):
        return "abc"

    async def latest(_repo, _ref):
        return remote

    monkeypatch.setattr(snapshot, "_community_local_head", local)
    monkeypatch.setattr(snapshot, "_community_remote_head", latest)

    _plugin_id, result = await snapshot._check_community(
        {"plugin_id": "demo", "repository_url": "repo", "ref": "main"},
    )

    assert result["has_update"] is expected


@pytest.mark.asyncio
async def test_check_community_reports_unknown_when_remote_command_raises(monkeypatch):
    async def local(_plugin_id):
        return "abc"

    async def failed_git(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(snapshot, "_community_local_head", local)
    monkeypatch.setattr("pallas.console.webui.community_plugin_install.run_git_command", failed_git)

    _plugin_id, result = await snapshot._check_community(
        {"plugin_id": "demo", "repository_url": "repo", "ref": "main"},
    )

    assert result["has_update"] is None
    assert result["error"] == "远端版本获取失败"


@pytest.mark.asyncio
async def test_remote_head_matches_git_clone_branch_and_tag_resolution(tmp_path):
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    clone = tmp_path / "clone"

    def git(*args):
        return subprocess.run(
            (
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.test",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                *args,
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "--bare", str(remote))
    git("init", "-b", "main", str(repo))
    (repo / "file").write_text("branch\n", encoding="utf-8")
    git("-C", str(repo), "add", "file")
    git("-C", str(repo), "commit", "-m", "branch")
    branch_commit = git("-C", str(repo), "rev-parse", "HEAD")
    git("-C", str(repo), "branch", "release")
    (repo / "file").write_text("tag\n", encoding="utf-8")
    git("-C", str(repo), "commit", "-am", "tag")
    tag_commit = git("-C", str(repo), "rev-parse", "HEAD")
    git("-C", str(repo), "tag", "-a", "release", "-m", "annotated")
    git("-C", str(repo), "tag", "lightweight")
    git("-C", str(repo), "remote", "add", "origin", str(remote))
    git("-C", str(repo), "push", "origin", "refs/heads/main", "refs/heads/release", "--tags")
    git("clone", "--branch", "release", str(remote), str(clone))

    assert git("-C", str(clone), "rev-parse", "HEAD") == branch_commit
    assert await snapshot._community_remote_head(str(remote), "release") == branch_commit
    assert await snapshot._community_remote_head(str(remote), "refs/tags/release") == tag_commit
    assert await snapshot._community_remote_head(str(remote), "lightweight") == tag_commit
