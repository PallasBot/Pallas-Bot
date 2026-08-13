"""AI Runtime 安装状态、受控 clone、连接写回。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pallas.console.cli import ai_install
from pallas.console.webui import ai_install_writeback as writeback


def test_ai_install_status_shape(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_AI_ROOT", str(tmp_path / "missing"))
    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: None)
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.probe_ai_health_at",
        lambda host, port, timeout_sec=3.0: {
            "ok": False,
            "url": f"http://{host}:{port}/health",
            "status_code": None,
            "body_preview": None,
            "error": "down",
        },
    )
    monkeypatch.setattr("pallas.console.cli.ai_supervisor.running_in_docker", lambda: False)
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.resolve_configured_ai_endpoint",
        lambda: ("127.0.0.1", 9099),
    )
    st = ai_install.ai_install_status()
    assert st["detected"] is False
    assert st["git_url"].endswith("Pallas-Bot-AI.git")
    assert "deploy/docker" in st["docker_hint"]
    assert "pallasbot-ai" in st["docker_hint"]
    assert st["clone_target"] == str((tmp_path / "missing").resolve())
    assert st["layout"] == "missing"
    assert st["is_managed"] is False
    assert st["runtime"]["can_manage"] is False
    assert st["runtime"]["running"] is False
    assert st["can_clone"] is True or st["git_available"] is False
    assert st["has_update"] is None
    assert "managed_root" in st
    assert "sibling_root" in st


def test_ai_install_status_docker_remote_healthy(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_AI_ROOT", str(tmp_path / "missing"))
    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: None)
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr("pallas.console.cli.ai_supervisor.running_in_docker", lambda: True)
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.resolve_configured_ai_endpoint",
        lambda: ("pallasbot-ai", 9099),
    )
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.probe_ai_health_at",
        lambda host, port, timeout_sec=3.0: {
            "ok": True,
            "url": f"http://{host}:{port}/health",
            "status_code": 200,
            "body_preview": '{"status":"ok"}',
            "error": None,
        },
    )
    st = ai_install.ai_install_status()
    assert st["detected"] is True
    assert st["can_clone"] is False
    assert st["layout"] == "docker"
    assert st["runtime"]["running"] is True
    assert st["runtime"]["can_manage"] is False
    assert st["endpoint"]["host"] == "pallasbot-ai"


def test_ai_install_status_forbids_clone_when_compose_host(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_AI_ROOT", str(tmp_path / "missing"))
    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: None)
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr("pallas.console.cli.ai_supervisor.running_in_docker", lambda: False)
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.resolve_configured_ai_endpoint",
        lambda: ("pallasbot-ai", 9099),
    )
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.probe_ai_health_at",
        lambda host, port, timeout_sec=3.0: {
            "ok": False,
            "url": f"http://{host}:{port}/health",
            "status_code": None,
            "body_preview": None,
            "error": "down",
        },
    )
    st = ai_install.ai_install_status()
    assert st["can_clone"] is False
    assert st["layout"] == "docker"


def test_default_clone_target_is_managed_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("PALLAS_AI_ROOT", raising=False)
    managed = tmp_path / "runtimes" / "pallas-bot-ai"
    monkeypatch.setattr(ai_install, "managed_ai_root", lambda: managed.resolve())
    assert ai_install.default_ai_clone_target() == managed.resolve()


def test_clone_ai_repo_marks_managed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = tmp_path / "pallas-bot-ai"
    monkeypatch.setattr(ai_install, "default_ai_clone_target", lambda: allowed.resolve())

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        dest = Path(cmd[-1])
        (dest / "scripts").mkdir(parents=True)
        (dest / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ai_install.subprocess, "run", fake_run)
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    out = ai_install.clone_ai_repo()
    assert out == allowed.resolve()
    assert (out / ".pallas-managed").is_file()


def test_clone_ai_repo_rejects_foreign_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = tmp_path / "Pallas-Bot-AI"
    monkeypatch.setattr(ai_install, "default_ai_clone_target", lambda: allowed.resolve())
    with pytest.raises(ValueError, match="受控路径"):
        ai_install.clone_ai_repo(target=tmp_path / "other")


def test_clone_ai_repo_rejects_existing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = tmp_path / "Pallas-Bot-AI"
    allowed.mkdir()
    (allowed / "scripts").mkdir()
    (allowed / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ai_install, "default_ai_clone_target", lambda: allowed.resolve())
    with pytest.raises(FileExistsError):
        ai_install.clone_ai_repo()


def test_update_ai_repo_ff_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "pallas-bot-ai"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".pallas-managed").write_text("managed-by=pallas-bot\n", encoding="utf-8")
    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: root.resolve())
    monkeypatch.setattr(ai_install, "forbid_ai_clone", lambda **_: False)
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.is_managed_ai_root",
        lambda p: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.mark_ai_root_managed",
        lambda _p: None,
    )

    calls: list[tuple[str, ...]] = []
    head_reads = {"n": 0}

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        del kwargs
        calls.append(tuple(cmd))
        args = tuple(cmd[1:])
        out = ""
        if args == ("rev-parse", "HEAD"):
            head_reads["n"] += 1
            out = "aaa111\n" if head_reads["n"] == 1 else "bbb222\n"
        elif args[:1] == ("rev-parse",) and "--abbrev-ref" in args:
            out = "origin/main\n"
        return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    monkeypatch.setattr(ai_install.subprocess, "run", fake_run)
    result = ai_install.update_ai_repo(ai_root=root)
    assert result["before"] == "aaa111"
    assert result["after"] == "bbb222"
    assert result["changed"] is True
    assert ("git", "pull", "--ff-only", "--autostash") in calls
    assert ("git", "submodule", "update", "--init", "--recursive") in calls


def test_update_ai_repo_rejects_unmanaged(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "sibling-ai"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / ".git").mkdir()
    monkeypatch.setattr(ai_install, "forbid_ai_clone", lambda **_: False)
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.is_managed_ai_root",
        lambda _p: False,
    )
    with pytest.raises(PermissionError, match="托管"):
        ai_install.update_ai_repo(ai_root=root)


def test_update_ai_repo_recovers_dirty_gitmodules(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """脏 .gitmodules（镜像 URL）不阻塞更新；冲突标记被清除，URL 覆盖写回本地 git 配置。"""
    git = shutil.which("git")
    if not git:
        pytest.skip("git 不可用")

    def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
        cp = subprocess.run(
            [git, *args],
            cwd=str(cwd) if cwd else None,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return cp.stdout.strip()

    sub_src = tmp_path / "sub-src"
    subprocess.run([git, "init", "-q", "-b", "main", str(sub_src)], check=True)
    _git("config", "user.email", "t@t", cwd=sub_src)
    _git("config", "user.name", "t", cwd=sub_src)
    _git("commit", "-q", "--allow-empty", "-m", "sub", cwd=sub_src)
    sub_sha = _git("rev-parse", "HEAD", cwd=sub_src)
    sub_bare = tmp_path / "sub-bare.git"
    subprocess.run([git, "clone", "-q", "--bare", str(sub_src), str(sub_bare)], check=True)
    upstream = tmp_path / "upstream"
    subprocess.run([git, "init", "-q", "-b", "main", str(upstream)], check=True)
    _git("config", "user.email", "t@t", cwd=upstream)
    _git("config", "user.name", "t", cwd=upstream)
    _git("commit", "-q", "--allow-empty", "-m", "base", cwd=upstream)
    (upstream / ".gitmodules").write_text(
        f'[submodule "engine"]\n\tpath = engine\n\turl = {sub_bare}\n',
        encoding="utf-8",
    )
    _git("add", ".gitmodules", cwd=upstream)
    subprocess.run(
        [git, "update-index", "--add", "--cacheinfo", f"160000,{sub_sha},engine"],
        cwd=upstream,
        check=True,
    )
    _git("commit", "-q", "-m", "add engine", cwd=upstream)

    root = tmp_path / "managed-ai"
    subprocess.run([git, "clone", "-q", str(upstream), str(root)], check=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    # 测试环境无 HTTP 远端，放行 file:// 让子模块克隆走本地裸仓
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")

    (root / ".gitmodules").write_text(
        '[submodule "engine"]\n\tpath = engine\n\turl = https://mirror.example/engine.git\n',
        encoding="utf-8",
    )
    (upstream / ".gitmodules").write_text(
        f'[submodule "engine"]\n\tpath = engine\n\turl = {sub_bare}\n'
        f'[submodule "engine2"]\n\tpath = engine2\n\turl = {sub_bare}\n',
        encoding="utf-8",
    )
    _git("add", ".gitmodules", cwd=upstream)
    subprocess.run(
        [git, "update-index", "--add", "--cacheinfo", f"160000,{sub_sha},engine2"],
        cwd=upstream,
        check=True,
    )
    _git("commit", "-q", "-m", "add engine2", cwd=upstream)

    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: root.resolve())
    monkeypatch.setattr(ai_install, "forbid_ai_clone", lambda **_: False)
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: git)
    monkeypatch.setattr("pallas.console.cli.ai_supervisor.is_managed_ai_root", lambda _p: True)
    monkeypatch.setattr("pallas.console.cli.ai_supervisor.mark_ai_root_managed", lambda _p: None)

    result = ai_install.update_ai_repo(ai_root=root)

    assert result["changed"] is True
    assert result["submodule_ok"] is True
    assert "gitmodules_notes" in result
    assert ".gitmodules" not in _git("status", "--porcelain", cwd=root)
    gm = (root / ".gitmodules").read_text(encoding="utf-8")
    assert "<<<<<<<" not in gm
    assert "mirror.example" not in gm
    assert _git("config", "submodule.engine.url", cwd=root) == "https://mirror.example/engine.git"
    assert not list(root.glob(".gitmodules.pallas.bak.*"))


def test_ai_install_status_can_update(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "managed-ai"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / ".git").mkdir()
    monkeypatch.setenv("PALLAS_AI_ROOT", str(root))
    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: root.resolve())
    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(ai_install, "forbid_ai_clone", lambda **_: False)
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.is_managed_ai_root",
        lambda p: p is not None,
    )
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.probe_ai_health_at",
        lambda host, port, timeout_sec=3.0: {
            "ok": False,
            "url": f"http://{host}:{port}/health",
            "status_code": None,
            "body_preview": None,
            "error": "down",
        },
    )
    monkeypatch.setattr("pallas.console.cli.ai_supervisor.running_in_docker", lambda: False)
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.resolve_configured_ai_endpoint",
        lambda: ("127.0.0.1", 9099),
    )
    monkeypatch.setattr(
        ai_install,
        "probe_ai_repo_update",
        lambda _root, **_: {
            "has_update": True,
            "installed_ref": "abc123456789",
            "latest_ref": "def123456789",
            "upstream": "origin/main",
            "error": None,
        },
    )
    st = ai_install.ai_install_status()
    assert st["can_update"] is True
    assert st["can_bootstrap"] is True
    assert st["can_clone"] is False
    assert st["has_update"] is True
    assert st["installed_ref"] == "abc123456789"
    assert st["latest_ref"] == "def123456789"
    assert st["update_check_error"] is None


def test_probe_ai_repo_update_compares_head(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "ai"
    (root / ".git").mkdir(parents=True)

    def fake_git_run(_cwd, *args, timeout_sec=None):  # noqa: ANN001
        del timeout_sec
        cmd = list(args)
        from types import SimpleNamespace

        if cmd[:2] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="aaa111\n", stderr="")
        if cmd[:3] == ["fetch", "--prune", "origin"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["rev-parse", "--abbrev-ref", "@{u}"]:
            return SimpleNamespace(returncode=0, stdout="origin/main\n", stderr="")
        if cmd[:2] == ["rev-parse", "origin/main"]:
            return SimpleNamespace(returncode=0, stdout="bbb222\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(ai_install, "_git_run", fake_git_run)
    out = ai_install.probe_ai_repo_update(root)
    assert out["has_update"] is True
    assert out["installed_ref"] == "aaa111"
    assert out["latest_ref"] == "bbb222"
    assert out["upstream"] == "origin/main"
    assert out["error"] is None


def test_probe_ai_repo_update_latest(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "ai"
    (root / ".git").mkdir(parents=True)

    def fake_git_run(_cwd, *args, timeout_sec=None):  # noqa: ANN001
        del timeout_sec
        cmd = list(args)
        from types import SimpleNamespace

        if cmd[:2] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="samehash0001\n", stderr="")
        if cmd[:3] == ["fetch", "--prune", "origin"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["rev-parse", "--abbrev-ref", "@{u}"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="no upstream")
        if cmd[:3] == ["rev-parse", "--verify", "origin/main"]:
            return SimpleNamespace(returncode=0, stdout="samehash0001\n", stderr="")
        if cmd[:2] == ["rev-parse", "origin/main"]:
            return SimpleNamespace(returncode=0, stdout="samehash0001\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(ai_install, "_git_run", fake_git_run)
    out = ai_install.probe_ai_repo_update(root)
    assert out["has_update"] is False
    assert out["installed_ref"] == "samehash0001"
    assert out["latest_ref"] == "samehash0001"
    assert out["error"] is None


def test_probe_ai_repo_update_fetch_fail(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "ai"
    (root / ".git").mkdir(parents=True)

    def fake_git_run(_cwd, *args, timeout_sec=None):  # noqa: ANN001
        del timeout_sec
        cmd = list(args)
        from types import SimpleNamespace

        if cmd[:2] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="aaa111\n", stderr="")
        if cmd[:3] == ["fetch", "--prune", "origin"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="network down")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr(ai_install.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(ai_install, "_git_run", fake_git_run)
    out = ai_install.probe_ai_repo_update(root)
    assert out["has_update"] is None
    assert out["installed_ref"] == "aaa111"
    assert "network down" in (out["error"] or "")


def test_writeback_ai_extension_creates_missing_file(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    assert writeback.writeback_ai_extension_if_empty(path=path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://127.0.0.1:9099"
    assert data["api_prefix"] == "/api"


def test_writeback_ai_extension_fills_empty_base_url(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    path.write_text(
        json.dumps({"base_url": "", "token": "keep-me", "api_prefix": "/api"}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert writeback.writeback_ai_extension_if_empty(path=path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://127.0.0.1:9099"
    assert data["token"] == "keep-me"


def test_writeback_ai_extension_preserves_custom_base_url(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    path.write_text(
        json.dumps({"base_url": "http://10.0.0.2:9199", "token": "x"}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert writeback.writeback_ai_extension_if_empty(path=path) is False
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://10.0.0.2:9199"


def test_writeback_ai_server_only_when_both_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    # clear cache that may have loaded other paths
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.writeback_ai_server_if_missing() is True
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env["AI_SERVER_HOST"] == "127.0.0.1"
    assert env["AI_SERVER_PORT"] == "9099"

    assert writeback.writeback_ai_server_if_missing() is False


def test_writeback_ai_server_skips_when_any_key_exists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(
        json.dumps({"env": {"AI_SERVER_HOST": "10.0.0.9"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.writeback_ai_server_if_missing() is False
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env == {"AI_SERVER_HOST": "10.0.0.9"}


def test_apply_ai_install_connection_writeback(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    ext = tmp_path / "ai_extension.json"
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    flags = writeback.apply_ai_install_connection_writeback(extension_path=ext)
    assert flags == {"wrote_ai_extension": True, "wrote_ai_server": True}
    assert ext.is_file()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://127.0.0.1:9099", ("127.0.0.1", "9099")),
        ("https://ai.example.com", ("ai.example.com", "443")),
        ("http://pallasbot-ai", ("pallasbot-ai", "9099")),
        ("10.0.0.2:9199", ("10.0.0.2", "9199")),
        ("", None),
    ],
)
def test_parse_ai_server_from_base_url(base_url: str, expected: tuple[str, str] | None) -> None:
    assert writeback.parse_ai_server_from_base_url(base_url) == expected


def test_sync_ai_server_from_extension_base_url(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.sync_ai_server_from_extension_base_url("http://pallasbot-ai:9099") is True
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env["AI_SERVER_HOST"] == "pallasbot-ai"
    assert env["AI_SERVER_PORT"] == "9099"


def test_sync_tts_token_from_extension_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.sync_tts_token_from_extension_token("secret-bearer") is True
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env["TTS_API_TOKEN"] == "secret-bearer"
    assert writeback.sync_tts_token_from_extension_token("secret-bearer") is False
    assert writeback.sync_tts_token_from_extension_token("") is True
    env2 = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env2.get("TTS_API_TOKEN", "") == ""


def test_sync_extension_base_url_from_ai_server_preserves_token(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:9099",
                "token": "keep",
                "api_prefix": "/api",
                "health_paths": ["/health"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert writeback.sync_extension_base_url_from_ai_server("pallasbot-ai", 9099, path=path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://pallasbot-ai:9099"
    assert data["token"] == "keep"
    assert writeback.sync_extension_base_url_from_ai_server("pallasbot-ai", 9099, path=path) is False
