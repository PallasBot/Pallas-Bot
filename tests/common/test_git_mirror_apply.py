from __future__ import annotations

import subprocess

import pytest

from pallas.core.shared.utils import git_mirror as gm
from pallas.core.shared.utils.git_mirror import BUILTIN_MIRRORS


def run_git(cwd, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def init_plugin_repo(root, plugin_id: str, remote_url: str) -> None:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text("# plugin\n", encoding="utf-8")
    assert run_git(plugin_dir, "init").returncode == 0
    assert run_git(plugin_dir, "remote", "add", "origin", remote_url).returncode == 0


def get_origin_url(root, plugin_id: str) -> str:
    proc = run_git(root / plugin_id, "remote", "get-url", "origin")
    assert proc.returncode == 0
    return proc.stdout.strip()


@pytest.fixture
def plugins_root(monkeypatch, tmp_path):
    root = tmp_path / "local" / "plugins"
    root.mkdir(parents=True)
    monkeypatch.setattr("pallas.console.webui.community_plugin_install.community_plugins_root", lambda: root)
    return root


def test_detect_mirror_id_variants():
    ghproxy = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    proxied = f"{ghproxy.clone_prefix}/PallasBot/Pallas-Bot.git"
    assert gm.detect_mirror_id("https://github.com/a/b.git") == "github"
    assert gm.detect_mirror_id(proxied) == "ghproxy-vip"
    assert gm.detect_mirror_id("https://proxy.example/https://github.com/a/b.git") == "custom"
    assert gm.detect_mirror_id("git@github.com:a/b.git") == "ssh"
    assert gm.detect_mirror_id("https://gitlab.com/a/b.git") == "unknown"


def test_canonical_github_https_url_strips_proxy():
    ghproxy = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    proxied = f"{ghproxy.clone_prefix}/owner/repo.git"
    assert gm.canonical_github_https_url(proxied) == "https://github.com/owner/repo.git"
    assert gm.canonical_github_https_url("git@github.com:owner/repo.git") == "https://github.com/owner/repo.git"
    assert gm.canonical_github_https_url("https://gitlab.com/a/b.git") is None


def test_apply_mirror_to_plugin_sets_proxy_then_github(plugins_root, monkeypatch, tmp_path):
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"ghproxy-vip","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    init_plugin_repo(plugins_root, "demo_plugin", "https://github.com/a/b.git")

    result = gm.apply_mirror_to_plugin("demo_plugin")
    assert result["success"] is True
    origin = get_origin_url(plugins_root, "demo_plugin")
    assert origin.startswith("https://ghproxy.vip/https://github.com/a/b")

    monkeypatch.setattr(
        gm,
        "load_git_mirror_config",
        lambda: {"preferred_id": "github", "custom_proxy_prefix": ""},
    )
    result2 = gm.apply_mirror_to_plugin("demo_plugin")
    assert result2["success"] is True
    assert get_origin_url(plugins_root, "demo_plugin") == "https://github.com/a/b.git"


def test_apply_mirror_to_community_plugins_summary(plugins_root, monkeypatch, tmp_path):
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"ghproxy-vip","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    init_plugin_repo(plugins_root, "one", "https://github.com/a/one.git")
    init_plugin_repo(plugins_root, "two", "https://github.com/a/two.git")
    (plugins_root / "not_git").mkdir()
    (plugins_root / "not_git" / "__init__.py").write_text("", encoding="utf-8")

    payload = gm.apply_mirror_to_community_plugins()
    summary = payload["summary"]
    assert summary["total"] == 3
    assert summary["success_count"] == 2
    assert summary["fail_count"] == 1

    info = gm.list_community_plugin_git_info()
    by_id = {row["id"]: row for row in info}
    assert by_id["one"]["is_git_repo"] is True
    assert by_id["one"]["mirror"] == "ghproxy-vip"
    assert by_id["not_git"]["is_git_repo"] is False


def test_list_community_plugin_git_info_empty_when_root_missing(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setattr("pallas.console.webui.community_plugin_install.community_plugins_root", lambda: missing)
    assert gm.list_community_plugin_git_info() == []
