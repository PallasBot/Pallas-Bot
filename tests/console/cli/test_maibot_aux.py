"""Focused tests for managed MaiBot aux: config, preflight, real spawn/stop."""

from __future__ import annotations

import hashlib
import socket
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from pallas.console.cli import maibot_assets, maibot_aux
from pallas.console.cli import maibot_dashboard
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

BRIDGE_KEYS = {
    "MAIBOT_MANAGED_ENABLED": "true",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _bridge(url: str, *, enabled: bool = True) -> MaiBotBridgeConfig:
    return MaiBotBridgeConfig(
        enabled=enabled,
        url=url,
        bot_id=10001,
        group_ids=frozenset({700001}),
        platform="pallas-qq",
        token="bridge-token",
    )


@pytest.fixture(autouse=True)
def _managed_runtime_fixtures(monkeypatch):
    original, patched = b"compat original\n", b"compat patched\n"
    monkeypatch.setattr(
        maibot_aux.native_compat,
        "PATCHES",
        tuple(
            replace(
                spec,
                original_sha256=hashlib.sha256(original).hexdigest(),
                patched_sha256=hashlib.sha256(patched).hexdigest(),
                edits=((original.decode(), patched.decode()),),
            )
            for spec in maibot_aux.native_compat.PATCHES
        ),
    )
    monkeypatch.setattr(maibot_aux, "_effective_config_ready", lambda _instance: True)
    monkeypatch.setattr(maibot_aux, "_config_sync_enabled", lambda: False)
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda _root: True)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _make_instance(root: Path, *, port: int, bot_py: str | None = None, eula: str = "eula text") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(exist_ok=True)
    (root / "EULA.md").write_text(eula, encoding="utf-8")
    (root / "PRIVACY.md").write_text("privacy text", encoding="utf-8")
    (root / "eula.confirmed").write_text(_md5(eula), encoding="utf-8")
    (root / "privacy.confirmed").write_text(_md5("privacy text"), encoding="utf-8")
    (root / "config" / "bot_config.toml").write_text(
        f'[maim_message]\nws_server_host = "127.0.0.1"\nws_server_port = {port}\nauth_token = "bridge-token"\n',
        encoding="utf-8",
    )
    (root / "config" / "model_config.toml").write_text("[models]\n", encoding="utf-8")
    if bot_py is None:
        bot_py = (
            "import socket, time\n"
            "s = socket.socket()\n"
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            f"s.bind(('127.0.0.1', {port}))\n"
            "s.listen()\n"
            "while True:\n"
            "    time.sleep(0.5)\n"
        )
    (root / "bot.py").write_text(bot_py, encoding="utf-8")
    for spec in maibot_aux.native_compat.PATCHES:
        path = root / spec.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"compat original\n")
    maibot_aux.native_compat.apply_native_compat(root)
    maibot_assets.deploy_assets(root)
    return root


def _patch_env(monkeypatch, *, enabled="true", instance_dir=None, python=None, bridge_url=None, bridge_enabled=True):
    values = {"MAIBOT_MANAGED_ENABLED": enabled}
    if instance_dir is not None:
        values["MAIBOT_MANAGED_DIR"] = str(instance_dir)
    if python is not None:
        values["MAIBOT_MANAGED_PYTHON"] = str(python)
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda key: values.get(key))
    url = bridge_url if bridge_url is not None else "ws://127.0.0.1:8000/ws"
    monkeypatch.setattr(
        "pallas.product.agent_bridge.config.load_bridge_config",
        lambda: _bridge(url, enabled=bridge_enabled),
    )


def _patch_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(maibot_aux, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(maibot_aux, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(maibot_aux, "PID_FILE", tmp_path / "run" / "maibot.pid")
    monkeypatch.setattr(maibot_aux, "OWNER_FILE", tmp_path / "run" / "maibot.owner.json")
    monkeypatch.setattr(maibot_aux, "LOG_FILE", tmp_path / "logs" / "maibot.log")


# ---------------------------------------------------------------- config


def test_default_disabled(monkeypatch):
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda _key: None)
    assert maibot_aux.load_managed_config().enabled is False
    assert maibot_aux.load_managed_config().enabled is False


def test_disabled_does_not_spawn(monkeypatch, tmp_path):
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda _key: None)
    _patch_paths(monkeypatch, tmp_path)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux().rc == 0
    assert spawned == []


def test_invalid_enabled_value_raises(monkeypatch):
    monkeypatch.setattr(
        maibot_aux, "repo_env_raw_value", lambda key: "maybe" if key == "MAIBOT_MANAGED_ENABLED" else None
    )
    with pytest.raises(maibot_aux.ManagedConfigError):
        maibot_aux.load_managed_config()


def test_enabled_without_dir_raises(monkeypatch):
    monkeypatch.setattr(
        maibot_aux,
        "repo_env_raw_value",
        lambda key: "true" if key == "MAIBOT_MANAGED_ENABLED" else None,
    )
    with pytest.raises(maibot_aux.ManagedConfigError):
        maibot_aux.load_managed_config()


def test_default_python_per_platform(tmp_path: Path):
    python = maibot_aux.default_managed_python(tmp_path)
    assert python.parent.name in {"bin", "Scripts"}


# ---------------------------------------------------------------- preflight


def test_preflight_bridge_disabled(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_enabled=False)
    config = maibot_aux.load_managed_config()
    bridge = _bridge("ws://127.0.0.1:8000/ws", enabled=False)
    assert (
        any("ws_server_port" in p or "桥" in p for p in maibot_aux.validate_managed_instance(config, bridge)) is False
    )
    # bridge disabled is rejected at start, not in instance validation
    _patch_paths(monkeypatch, tmp_path)
    assert maibot_aux.start_maibot_aux().rc == 1


@pytest.mark.parametrize(
    ("bridge_url", "reason"),
    [
        ("wss://127.0.0.1:8000/ws", "loopback"),
        ("ws://10.0.0.5:8000/ws", "loopback"),
        ("ws://127.0.0.1:9999/ws", "不一致"),
    ],
)
def test_preflight_rejects_nonlocal_or_mismatched(monkeypatch, tmp_path, bridge_url, reason):
    instance = _make_instance(tmp_path / "inst", port=8000)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=bridge_url)
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge(bridge_url))
    assert any(reason in problem for problem in problems), problems


def test_preflight_missing_protocol_confirmation(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    (instance / "eula.confirmed").unlink()
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url="ws://127.0.0.1:8000/ws")
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws"))
    assert any("未确认协议" in problem for problem in problems)


def test_preflight_protocol_hash_change(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    (instance / "EULA.md").write_text("changed", encoding="utf-8")
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url="ws://127.0.0.1:8000/ws")
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws"))
    assert any("协议已变更" in problem for problem in problems)


def test_preflight_missing_entry_and_python(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    (instance / "bot.py").unlink()
    _patch_env(
        monkeypatch, instance_dir=instance, python=tmp_path / "missing-python", bridge_url="ws://127.0.0.1:8000/ws"
    )
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws"))
    assert any("bot.py" in problem for problem in problems)
    assert any("解释器" in problem for problem in problems)


def test_validate_requires_patched_source_plugin_assets_and_ready_model_config(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=instance, python=Path(sys.executable))
    bridge = _bridge("ws://127.0.0.1:8000/ws")
    plugin_source = instance / "plugins" / maibot_assets.PLUGIN_DIR_NAME / "plugin.py"
    plugin_source.unlink()
    compat_source = instance / maibot_aux.native_compat.PATCHES[0].relative_path
    compat_source.write_bytes(b"external edit")

    problems = maibot_aux.validate_managed_instance(config, bridge)
    assert any("兼容补丁" in problem for problem in problems)
    assert any("插件资产" in problem for problem in problems)

    for spec in maibot_aux.native_compat.PATCHES:
        (instance / spec.relative_path).write_bytes(b"compat original\n")
    maibot_aux.native_compat.apply_native_compat(instance)
    instance = _make_instance(tmp_path / "ready", port=8000)
    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=instance, python=Path(sys.executable))
    monkeypatch.setattr(maibot_aux, "_effective_config_ready", lambda _instance: False)
    problems = maibot_aux.validate_managed_instance(config, bridge)
    assert problems == ["MaiBot 原生模型配置未就绪，拒绝启动"]


def test_validate_requires_exact_bridge_auth_token(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=instance, python=Path(sys.executable))
    bridge = MaiBotBridgeConfig(
        enabled=True,
        url="ws://127.0.0.1:8000/ws",
        bot_id=10001,
        group_ids=frozenset({700001}),
        platform="pallas-qq",
        token="different-token",
    )
    problems = maibot_aux.validate_managed_instance(config, bridge)
    assert any("认证 token" in problem for problem in problems)
    assert "different-token" not in "\n".join(problems)


def test_managed_platform_must_be_valid(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=instance, python=Path(sys.executable))
    bridge = replace(_bridge("ws://127.0.0.1:8000/ws"), platform="bad\nplatform")
    problems = maibot_aux.validate_managed_instance(config, bridge)
    joined = "\n".join(problems)
    assert "桥平台无效" in joined
    assert "bad\nplatform" not in joined


# ---------------------------------------------------------------- env


def test_build_managed_env_drops_and_sets(monkeypatch, tmp_path):
    for key in (
        "PYTHONPATH",
        "MAIBOT_WORKER_PROCESS",
        "MAIBOT_INSTANCE_DIR",
        "EULA_AGREE",
        "PRIVACY_AGREE",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "APP_SECRET",
        "PALLAS_MAIBOT_PYTHON",
    ):
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")
    for key, value in {
        "PATH": "/fixture/bin",
        "HOME": str(tmp_path / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": str(tmp_path),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "SSL_CERT_FILE": str(tmp_path / "ca.pem"),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PALLAS_MAIBOT_PROVIDER_URL", "http://attacker.invalid")
    monkeypatch.setenv("PALLAS_MAIBOT_PROVIDER_OTHER", "attacker")
    monkeypatch.setenv("PALLAS_MAIBOT_MENTION_PLATFORM", "attacker")
    env = maibot_aux.build_managed_env(tmp_path / "inst")
    for key in (
        "PYTHONPATH",
        "MAIBOT_WORKER_PROCESS",
        "EULA_AGREE",
        "PRIVACY_AGREE",
        "VIRTUAL_ENV",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "APP_SECRET",
        "PALLAS_MAIBOT_PYTHON",
    ):
        assert key not in env
    assert {
        key: env[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "XDG_CACHE_HOME", "SSL_CERT_FILE")
    } == {
        "PATH": "/fixture/bin",
        "HOME": str(tmp_path / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": str(tmp_path),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "SSL_CERT_FILE": str(tmp_path / "ca.pem"),
    }
    assert env["MAIBOT_INSTANCE_DIR"] == str(tmp_path / "inst")
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert not any(key.startswith("PALLAS_MAIBOT_PROVIDER_") for key in env)
    assert maibot_aux.MENTION_PLATFORM_ENV not in env

    env = maibot_aux.build_managed_env(
        tmp_path / "inst",
        mention_platform="pallas-qq",
    )
    assert not any(key.startswith("PALLAS_MAIBOT_PROVIDER_") for key in env)
    assert env[maibot_aux.MENTION_PLATFORM_ENV] == "pallas-qq"


@pytest.mark.parametrize("mention_platform", ["", " ", "pallas\nqq", "pallas\x00qq", 123])
def test_build_managed_env_rejects_invalid_explicit_platform(tmp_path, mention_platform):
    with pytest.raises(maibot_aux.ManagedConfigError, match="桥平台无效"):
        maibot_aux.build_managed_env(tmp_path, mention_platform=mention_platform)


# ---------------------------------------------------------------- real subprocess


async def test_real_spawn_ready_and_stop(monkeypatch, tmp_path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    try:
        result = maibot_aux.start_maibot_aux(ready_timeout_s=10.0)
        assert result.rc == 0
        pid = maibot_aux.read_pid_file(maibot_aux.PID_FILE)
        assert pid is not None
        assert result.spawned_pid == pid
        assert maibot_aux.pid_alive(pid)
        assert maibot_aux.maibot_aux_running() is True
        assert maibot_aux.current_managed_process() == pid
        # idempotent: no second spawn
        again = maibot_aux.start_maibot_aux(ready_timeout_s=5.0)
        assert again.rc == 0
        assert again.spawned_pid is None
        assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) == pid
        maibot_aux.stop_maibot_aux()
        assert maibot_aux.maibot_aux_running() is False
    finally:
        pid = maibot_aux.read_pid_file(maibot_aux.PID_FILE)
        if pid is not None:
            maibot_aux._stop_owned_pid(pid, force=True)
        maibot_aux.clear_pid_file(maibot_aux.PID_FILE)


async def test_unknown_port_occupant_is_refused(monkeypatch, tmp_path):
    port = _free_port()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    try:
        assert maibot_aux.start_maibot_aux(ready_timeout_s=1.0).rc == 1
        assert spawned == []
    finally:
        listener.close()


async def test_early_exit_rolls_back_this_pid(monkeypatch, tmp_path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port, bot_py="import sys\nsys.exit(3)\n")
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    assert maibot_aux.start_maibot_aux(ready_timeout_s=5.0).rc == 1
    assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) is None


async def test_timeout_rolls_back_this_pid(monkeypatch, tmp_path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port, bot_py="import time\nwhile True:\n    time.sleep(0.5)\n")
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    try:
        assert maibot_aux.start_maibot_aux(ready_timeout_s=0.8).rc == 1
        assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) is None
    finally:
        pid = maibot_aux.read_pid_file(maibot_aux.PID_FILE)
        if pid is not None:
            maibot_aux._stop_owned_pid(pid, force=True)


async def test_running_managed_pid_is_not_respawned(monkeypatch, tmp_path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: 4321)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    monkeypatch.setattr(maibot_aux, "_wait_transport_ready", lambda *a, **k: 0)
    result = maibot_aux.start_maibot_aux()
    assert result.rc == 0
    assert result.spawned_pid is None
    assert spawned == []


def test_invalid_bridge_platform_never_spawns(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        maibot_aux, "_load_bridge", lambda: (replace(_bridge("ws://127.0.0.1:8000/ws"), platform=""), None)
    )
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert spawned == []


def test_native_preflight_needs_no_provider_context_or_plugin(monkeypatch, tmp_path):
    import shutil

    instance = _make_instance(tmp_path / "native", port=8000)
    shutil.rmtree(instance / "plugins" / maibot_assets.PLUGIN_DIR_NAME)
    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=instance, python=Path(sys.executable))
    assert maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws")) == []


def test_native_child_env_sets_only_explicit_mention_platform(tmp_path):
    env = maibot_aux.build_managed_env(tmp_path, mention_platform="pallas-qq")
    assert env[maibot_aux.MENTION_PLATFORM_ENV] == "pallas-qq"
    assert not any(key.startswith("PALLAS_MAIBOT_PROVIDER_") for key in env)
    assert env["MAIBOT_WEBUI_USE_LOCAL_DASHBOARD"] == "1"


def test_preflight_refuses_missing_or_unverified_subpath_dashboard(monkeypatch, tmp_path):
    instance = _make_instance(tmp_path / "native", port=8000)
    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=instance, python=Path(sys.executable))
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda _root: False)
    problems = maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws"))
    assert any("子路径前端" in problem for problem in problems)


def test_status_lines(monkeypatch, capsys):
    monkeypatch.setattr(maibot_aux, "managed_runtime_state", lambda: "off")
    maibot_aux.print_maibot_aux_status()
    assert "MaiBot 托管" in capsys.readouterr().out


def test_status_shows_invalid_not_off(monkeypatch, capsys):
    def boom():
        raise maibot_aux.ManagedConfigError("bad")

    monkeypatch.setattr(maibot_aux, "load_managed_config", boom)
    maibot_aux.print_maibot_aux_status()
    out = capsys.readouterr().out
    assert "配置无效" in out
    assert "未开启" not in out
