from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pallas.console.cli import maibot_dashboard, maibot_install
from pallas.console.cli.main import build_parser, main
from pallas.product.agent_bridge import native_compat
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

if TYPE_CHECKING:
    from collections.abc import Callable

PIN = "062d45cf8bd4272ac57d7ec03fcf405e5a458211"
_COMPAT_ORIGINAL = b"compat original\n"
_COMPAT_PATCHED = b"compat patched\n"


def _make_compat_sources(root: Path) -> None:
    for spec in native_compat.PATCHES:
        path = root / spec.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_COMPAT_ORIGINAL)


@pytest.fixture(autouse=True)
def isolate_managed_process_state(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        native_compat,
        "PATCHES",
        tuple(
            replace(
                spec,
                original_sha256=hashlib.sha256(_COMPAT_ORIGINAL).hexdigest(),
                patched_sha256=hashlib.sha256(_COMPAT_PATCHED).hexdigest(),
                edits=((_COMPAT_ORIGINAL.decode(), _COMPAT_PATCHED.decode()),),
            )
            for spec in native_compat.PATCHES
        ),
    )
    aux = maibot_install.maibot_aux
    run_dir = tmp_path / "managed-run"
    monkeypatch.setattr(aux, "RUN_DIR", run_dir)
    monkeypatch.setattr(aux, "PID_FILE", run_dir / "maibot.pid")
    monkeypatch.setattr(aux, "OWNER_FILE", run_dir / "maibot.owner.json")
    monkeypatch.setattr(maibot_dashboard, "dashboard_state", lambda _root: "built")
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda _root: True)
    monkeypatch.setattr(maibot_dashboard, "apply_dashboard_compat", lambda *_args, **_kwargs: "patched")
    monkeypatch.setattr(maibot_dashboard, "build_dashboard", lambda _root: None)


def _successful_command(command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float) -> str:
    if command[:3] == ["git", "clone", "--no-checkout"]:
        target = Path(command[-1])
        (target / ".git").mkdir()
        _make_compat_sources(target)
        (target / "pyproject.toml").write_text('[project]\nname = "MaiBot"\n', encoding="utf-8")
        (target / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (target / "bot.py").write_text("", encoding="utf-8")
        (target / "EULA.md").write_text("EULA text", encoding="utf-8")
        (target / "PRIVACY.md").write_text("Privacy text", encoding="utf-8")
        (target / "LICENSE").write_text("AGPL", encoding="utf-8")
        license_dir = target / "src" / "A_memorix"
        license_dir.mkdir(parents=True)
        (license_dir / "LICENSE-MAIBOT-GPL.md").write_text("GPL", encoding="utf-8")
        return ""
    if command[:2] == ["git", "rev-parse"]:
        return PIN
    if command[:2] == ["git", "checkout"]:
        return ""
    if command[:2] == ["uv", "sync"]:
        python = maibot_install.maibot_aux.default_managed_python(cwd)
        python.parent.mkdir(parents=True, exist_ok=True)
        (python.parent.parent / "pyvenv.cfg").write_text("version = 3.12.8\n", encoding="utf-8")
        python.write_text("", encoding="utf-8")
        script = python.parent / ("maibot.exe" if python.suffix == ".exe" else "maibot")
        script.write_text(f"#!{python}\n", encoding="utf-8")
        script.chmod(0o755)
        return ""
    if command[:2] == ["uv", "run"]:
        config = cwd / "config"
        config.mkdir(exist_ok=True)
        for name, content in (
            ("bot_config.toml", "[maim_message]\nws_server_port = 8000\n"),
            ("model_config.toml", '[inner]\nversion = "1"\n'),
        ):
            path = config / name
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        return ""
    raise AssertionError(f"unexpected command: {command}")


def _patch_installer(monkeypatch, runner: Callable = _successful_command) -> None:
    monkeypatch.setattr(maibot_install.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(maibot_install, "run_command", runner)


def _set_managed_dir(monkeypatch, path: Path | None) -> None:
    value = str(path) if path is not None else None
    monkeypatch.setattr(
        maibot_install,
        "repo_env_raw_value",
        lambda key: value if key == maibot_install.MANAGED_DIR_KEY else None,
    )


def _read_marker(root: Path) -> dict[str, str]:
    return json.loads((root / maibot_install.INSTALL_MARKER_NAME).read_text(encoding="utf-8"))


def test_install_requires_actual_compat_patch_before_completion(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    assert native_compat.native_compat_state(target) == "patched"
    assert _read_marker(target)["state"] == "complete"
    assert maibot_install.install_maibot(target) == target


def test_native_install_does_not_deploy_provider_plugin_and_is_idempotent(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)

    def unexpected_deploy(_instance):
        raise AssertionError("Native model management must not install a Pallas model proxy")

    monkeypatch.setattr(maibot_install.maibot_assets, "deploy_assets", unexpected_deploy)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    assets_dir = target / "plugins" / maibot_install.maibot_assets.PLUGIN_DIR_NAME
    assert not assets_dir.exists()
    assert _read_marker(target)["state"] == "complete"
    assert maibot_install.installation_status(target) == "CLI 管理，complete"
    assert maibot_install.install_maibot(target) == target
    assert not assets_dir.exists()


def test_complete_install_status_and_retry_reject_missing_or_modified_assets(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    maibot_install.maibot_assets.deploy_assets(target)
    plugin = target / "plugins" / maibot_install.maibot_assets.PLUGIN_DIR_NAME / "plugin.py"
    original = plugin.read_bytes()
    plugin.write_bytes(original + b"\n# external edit\n")
    assert "外部修改" in maibot_install.installation_status(target)
    with pytest.raises(maibot_install.MaiBotInstallError, match="外部修改"):
        maibot_install.install_maibot(target)
    assert plugin.read_bytes() == original + b"\n# external edit\n"

    plugin.write_bytes(original)
    plugin.unlink()
    assert "插件资产缺失" in maibot_install.installation_status(target)
    with pytest.raises(maibot_install.MaiBotInstallError, match="缺失"):
        maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "complete"


def test_verified_managed_assets_upgrade_without_rewriting_unknown_contents(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    assets = maibot_install.maibot_assets
    assets.deploy_assets(target)
    current = assets._resource_assets()
    updated = {**current, "plugin.py": current["plugin.py"] + b"\n# packaged update\n"}
    monkeypatch.setattr(assets, "_resource_assets", lambda: updated)

    assets.deploy_assets(target)
    plugin = target / "plugins" / assets.PLUGIN_DIR_NAME / "plugin.py"
    assert plugin.read_bytes() == updated["plugin.py"]
    assert _read_marker(target)["state"] == "complete"


def test_managed_plugin_unknown_files_and_symlink_paths_are_not_overwritten(tmp_path):
    assets = maibot_install.maibot_assets
    unknown_instance = tmp_path / "unknown-instance"
    unknown_target = unknown_instance / "plugins" / assets.PLUGIN_DIR_NAME
    unknown_target.mkdir(parents=True)
    user_file = unknown_target / "user.py"
    user_file.write_text("user plugin", encoding="utf-8")
    with pytest.raises(assets.MaiBotAssetsError, match="未受 Pallas 管理"):
        assets.deploy_assets(unknown_instance)
    assert user_file.read_text(encoding="utf-8") == "user plugin"

    instance = tmp_path / "instance"
    assets.deploy_assets(instance)
    plugin_dir = instance / "plugins" / assets.PLUGIN_DIR_NAME
    extra = plugin_dir / "user.txt"
    extra.write_text("keep", encoding="utf-8")
    with pytest.raises(assets.MaiBotAssetsError, match="未知文件"):
        assets.deploy_assets(instance)
    assert extra.read_text(encoding="utf-8") == "keep"

    real = tmp_path / "real"
    assets.deploy_assets(real)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(assets.MaiBotAssetsError, match="符号链接"):
        assets.deploy_assets(linked)


def test_duplicate_plugin_id_is_rejected(tmp_path):
    assets = maibot_install.maibot_assets
    instance = tmp_path / "instance"
    duplicate = instance / "plugins" / "someone-else"
    duplicate.mkdir(parents=True)
    (duplicate / "_manifest.json").write_text(json.dumps({"id": assets.PLUGIN_ID}), encoding="utf-8")
    with pytest.raises(assets.MaiBotAssetsError, match="同 ID"):
        assets.deploy_assets(instance)


def test_asset_replacement_failure_restores_verified_old_directory(monkeypatch, tmp_path):
    assets = maibot_install.maibot_assets
    instance = tmp_path / "instance"
    assets.deploy_assets(instance)
    target = instance / "plugins" / assets.PLUGIN_DIR_NAME
    before = {path.name: path.read_bytes() for path in target.iterdir() if path.is_file()}
    current = assets._resource_assets()
    changed = {**current, "plugin.py": current["plugin.py"] + b"\n# new packaged revision\n"}
    monkeypatch.setattr(assets, "_resource_assets", lambda: changed)
    real_rename = Path.rename

    def fail_stage_publish(path, destination):
        if path.name.startswith(".pallas-maibot-assets-stage-") and Path(destination) == target:
            raise OSError("injected rename failure")
        return real_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_stage_publish)
    with pytest.raises(assets.MaiBotAssetsError, match="发布失败"):
        assets.deploy_assets(instance)
    assert {path.name: path.read_bytes() for path in target.iterdir() if path.is_file()} == before
    assert not list((instance / "plugins").glob(".pallas-maibot-assets-*"))


def test_backup_cleanup_failure_keeps_new_assets_committed(monkeypatch, tmp_path):
    assets = maibot_install.maibot_assets
    instance = tmp_path / "instance"
    assets.deploy_assets(instance)
    current = assets._resource_assets()
    updated = {**current, "plugin.py": current["plugin.py"] + b"\n# packaged update\n"}
    monkeypatch.setattr(assets, "_resource_assets", lambda: updated)
    real_rmtree = assets.shutil.rmtree
    backups: list[Path] = []

    def fail_backup_cleanup(path, *args, **kwargs):
        path = Path(path)
        if path.name.startswith(".pallas-maibot-assets-backup-"):
            backups.append(path)
            (path / "plugin.py").unlink()
            raise OSError("injected partial cleanup failure")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(assets.shutil, "rmtree", fail_backup_cleanup)
    with pytest.raises(assets.MaiBotAssetsError, match="已发布.*清理失败") as error:
        assets.deploy_assets(instance)
    assert assets.inspect_assets(instance) == "current"
    assert (instance / "plugins" / assets.PLUGIN_DIR_NAME / "plugin.py").read_bytes() == updated["plugin.py"]
    assert len(backups) == 1
    assert backups[0].parent == instance
    assert backups[0].is_dir()
    assert str(backups[0]) in str(error.value)


def test_failed_old_asset_restore_reports_incomplete_and_preserves_backup(monkeypatch, tmp_path):
    assets = maibot_install.maibot_assets
    instance = tmp_path / "instance"
    assets.deploy_assets(instance)
    target = instance / "plugins" / assets.PLUGIN_DIR_NAME
    before = {path.name: path.read_bytes() for path in target.iterdir() if path.is_file()}
    user_file = instance / "user-data.txt"
    user_file.write_text("keep", encoding="utf-8")
    current = assets._resource_assets()
    monkeypatch.setattr(
        assets, "_resource_assets", lambda: {**current, "plugin.py": current["plugin.py"] + b"\n# update\n"}
    )
    real_rename = Path.rename

    def fail_publish_and_restore(path, destination):
        destination = Path(destination)
        if destination == target and (
            path.name.startswith(".pallas-maibot-assets-stage-")
            or path.name.startswith(".pallas-maibot-assets-backup-")
        ):
            raise OSError("injected rename failure")
        return real_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_publish_and_restore)
    with pytest.raises(assets.MaiBotAssetsError, match="回滚不完整.*备份保留") as error:
        assets.deploy_assets(instance)
    backups = list(instance.glob(".pallas-maibot-assets-backup-*"))
    assert len(backups) == 1
    assert {path.name: path.read_bytes() for path in backups[0].iterdir() if path.is_file()} == before
    assert not target.exists()
    assert not list((instance / "plugins").glob(".pallas-maibot-assets-backup-*"))
    assert user_file.read_text(encoding="utf-8") == "keep"
    assert str(backups[0]) in str(error.value)


def test_native_install_is_independent_of_provider_asset_write_failures(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    original_write = Path.write_bytes

    def fail_asset_write(path, content):
        if path.parent.name.startswith(".pallas-maibot-assets-stage-") and path.name == "plugin.py":
            raise OSError("injected asset write failure")
        return original_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_asset_write)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "complete"
    assert not (target / "plugins" / maibot_install.maibot_assets.PLUGIN_DIR_NAME).exists()
    assert not list((target / "plugins").glob(".pallas-maibot-assets-*"))


def test_unknown_compat_source_preserves_incomplete_and_content(monkeypatch, tmp_path):
    target = tmp_path / "runtime"
    _make_incomplete_install(target)
    unknown = target / native_compat.PATCHES[0].relative_path
    unknown.write_bytes(b"unknown user changes\n")
    _patch_installer(monkeypatch)
    with pytest.raises(maibot_install.MaiBotInstallError, match="incomplete"):
        maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "incomplete"
    assert unknown.read_bytes() == b"unknown user changes\n"


def test_complete_marker_does_not_hide_missing_compat_patch(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    _make_compat_sources(target)
    assert "实际运行环境" in maibot_install.installation_status(target)
    with pytest.raises(maibot_install.MaiBotInstallError, match="完成标记"):
        maibot_install.install_maibot(target)


def test_complete_legacy_compat_install_upgrades_without_rewriting_configs(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    startup_source = target / native_compat.PATCHES[-1].relative_path
    startup_source.write_bytes(_COMPAT_ORIGINAL)
    configs = {
        target / "config" / "bot_config.toml": b"user bot config",
        target / "config" / "model_config.toml": b"user model config",
    }
    for path, content in configs.items():
        path.write_bytes(content)

    real_runner = _successful_command

    def runner(command, *, cwd, env, timeout):
        if command[:2] in (["uv", "sync"], ["uv", "run"]):
            assert _read_marker(target)["state"] == "incomplete"
        return real_runner(command, cwd=cwd, env=env, timeout=timeout)

    real_apply = native_compat.apply_native_compat
    observed_states: list[str] = []

    def apply(root: Path, *, expected_pin: str) -> str:
        assert _read_marker(root)["state"] == "incomplete"
        observed_states.append(native_compat.native_compat_state(root, expected_pin=expected_pin))
        return real_apply(root, expected_pin=expected_pin)

    monkeypatch.setattr(maibot_install, "run_command", runner)
    monkeypatch.setattr(maibot_install, "apply_native_compat", apply)
    assert native_compat.native_compat_state(target) == "upgradeable"

    assert maibot_install.install_maibot(target) == target

    assert observed_states == ["upgradeable"]
    assert native_compat.native_compat_state(target) == "patched"
    assert {path: path.read_bytes() for path in configs} == configs
    assert _read_marker(target)["state"] == "complete"


def test_compat_upgrade_failure_keeps_install_incomplete(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    (target / native_compat.PATCHES[-1].relative_path).write_bytes(_COMPAT_ORIGINAL)

    def fail_upgrade(root: Path, *, expected_pin: str) -> str:
        assert _read_marker(root)["state"] == "incomplete"
        raise native_compat.NativeCompatError("injected startup compatibility patch failure")

    monkeypatch.setattr(maibot_install, "apply_native_compat", fail_upgrade)
    with pytest.raises(maibot_install.MaiBotInstallError, match="incomplete"):
        maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "incomplete"
    assert native_compat.native_compat_state(target) == "upgradeable"


def test_compat_upgrade_must_change_sources_before_complete(monkeypatch, tmp_path):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    (target / native_compat.PATCHES[-1].relative_path).write_bytes(_COMPAT_ORIGINAL)

    def skip_upgrade(root: Path, *, expected_pin: str) -> str:
        assert _read_marker(root)["state"] == "incomplete"
        return "patched"

    monkeypatch.setattr(maibot_install, "apply_native_compat", skip_upgrade)
    with pytest.raises(maibot_install.MaiBotInstallError, match="incomplete"):
        maibot_install.install_maibot(target)
    assert native_compat.native_compat_state(target) == "upgradeable"
    assert _read_marker(target)["state"] == "incomplete"


@pytest.mark.parametrize("source_states", [("unknown", "patched", "patched"), ("original", "patched", "patched")])
def test_complete_install_rejects_unknown_or_mixed_compat_sources(monkeypatch, tmp_path, source_states):
    _patch_installer(monkeypatch)
    target = tmp_path / "runtime"
    maibot_install.install_maibot(target)
    for spec, state in zip(native_compat.PATCHES, source_states, strict=True):
        source = target / spec.relative_path
        source.write_bytes(
            b"unknown compatibility source\n"
            if state == "unknown"
            else {
                "original": _COMPAT_ORIGINAL,
                "patched": _COMPAT_PATCHED,
            }[state]
        )
    before = {spec.relative_path: (target / spec.relative_path).read_bytes() for spec in native_compat.PATCHES}
    calls: list[list[str]] = []

    def read_only_runner(command, *, cwd, env, timeout):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return PIN
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(maibot_install, "run_command", read_only_runner)
    with pytest.raises(maibot_install.MaiBotInstallError):
        maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "complete"
    assert {spec.relative_path: (target / spec.relative_path).read_bytes() for spec in native_compat.PATCHES} == before
    assert not any(command[:2] in (["uv", "sync"], ["uv", "run"]) for command in calls)


def _make_incomplete_install(root: Path) -> None:
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    _make_compat_sources(root)
    (root / "pyproject.toml").write_text('[project]\nname = "MaiBot"\n', encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "bot.py").write_text("", encoding="utf-8")
    (root / "EULA.md").write_text("EULA", encoding="utf-8")
    (root / "PRIVACY.md").write_text("Privacy", encoding="utf-8")
    (root / maibot_install.INSTALL_MARKER_NAME).write_text(
        json.dumps({
            "pin": PIN,
            "state": "incomplete",
            "dependency_hash": maibot_install.dependency_hash(root),
        }),
        encoding="utf-8",
    )


def test_cli_registers_install_status_terms_and_explicit_accept():
    parser = build_parser()
    args = parser.parse_args(["maibot", "install", "--dir", "/tmp/MaiBot with spaces"])
    assert args.handler.__name__ == "run_install"
    assert args.directory == Path("/tmp/MaiBot with spaces")
    assert parser.parse_args(["maibot", "status"]).handler.__name__ == "run_status"
    assert parser.parse_args(["maibot", "terms"]).handler.__name__ == "run_terms"
    with pytest.raises(SystemExit):
        parser.parse_args(["maibot", "accept", "--eula"])
    args = parser.parse_args(["maibot", "accept", "--eula", "--privacy"])
    assert args.handler.__name__ == "run_accept"


def test_default_path_and_configured_managed_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(maibot_install, "DATA_ROOT", tmp_path / "pallas-data")
    assert maibot_install.selected_maibot_dir() == tmp_path / "pallas-data" / "runtimes" / "maibot"
    configured = tmp_path / "configured instance"
    _set_managed_dir(monkeypatch, configured)
    assert maibot_install.selected_maibot_dir() == configured


def test_install_pins_source_syncs_frozen_and_uses_nested_environment(monkeypatch, tmp_path: Path):
    target = tmp_path / "MaiBot runtime"
    calls: list[tuple[list[str], Path, dict[str, str] | None, float]] = []

    def runner(command, *, cwd, env, timeout):
        calls.append((command, cwd, env, timeout))
        if command[:2] in (["uv", "sync"], ["uv", "run"]):
            assert cwd == target
            assert _read_marker(target)["state"] == "incomplete"
        return _successful_command(command, cwd=cwd, env=env, timeout=timeout)

    monkeypatch.setattr(maibot_install.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(maibot_install, "run_command", runner)
    monkeypatch.setenv("VIRTUAL_ENV", "/pallas/.venv")
    monkeypatch.setenv("UV_PROJECT", "/pallas")
    assert maibot_install.install_maibot(target) == target

    clone = next(call for call in calls if call[0][:2] == ["git", "clone"])
    assert clone[0] == ["git", "clone", "--no-checkout", maibot_install.UPSTREAM_URL, clone[0][-1]]
    source_stage = Path(clone[0][-1])
    checkout = next(call[0] for call in calls if call[0][:2] == ["git", "checkout"])
    assert checkout[-2:] == ["--detach", PIN]
    sync, sync_cwd, sync_env, _timeout = next(call for call in calls if call[0][:2] == ["uv", "sync"])
    assert sync == ["uv", "sync", "--frozen", "--no-dev"]
    assert sync_cwd == target
    assert sync_env is not None
    assert "VIRTUAL_ENV" not in sync_env
    assert "UV_PROJECT" not in sync_env
    init, init_cwd, init_env, _timeout = next(call for call in calls if call[0][:2] == ["uv", "run"])
    assert init == [
        "uv",
        "run",
        "--frozen",
        "--no-dev",
        "--no-sync",
        "--project",
        str(target),
        "maibot",
        "init",
        "--directory",
        str(target),
    ]
    assert init_cwd == target
    assert init_env is not None
    assert "VIRTUAL_ENV" not in init_env
    assert "UV_PROJECT" not in init_env
    assert (target / "config" / "bot_config.toml").is_file()
    assert (target / "config" / "model_config.toml").is_file()
    assert (target / "LICENSE").is_file()
    assert (target / "src" / "A_memorix" / "LICENSE-MAIBOT-GPL.md").is_file()
    assert not (target / "eula.confirmed").exists()
    assert _read_marker(target) == {
        "pin": PIN,
        "state": "complete",
        "dependency_hash": maibot_install.dependency_hash(target),
    }
    python = maibot_install.maibot_aux.default_managed_python(target)
    script = python.parent / "maibot"
    assert script.read_text(encoding="utf-8").splitlines()[0] == f"#!{python}"
    assert not source_stage.exists()
    configs_before = {
        name: (target / "config" / name).read_bytes() for name in ("bot_config.toml", "model_config.toml")
    }

    def no_reinstall(command, *, cwd, env, timeout):
        assert command[:2] == ["git", "rev-parse"]
        return PIN

    monkeypatch.setattr(maibot_install, "run_command", no_reinstall)
    maibot_install.install_maibot(target)
    assert {name: (target / "config" / name).read_bytes() for name in configs_before} == configs_before


def test_existing_unknown_target_and_symlink_are_never_taken_over(monkeypatch, tmp_path: Path):
    _patch_installer(monkeypatch)
    existing = tmp_path / "unknown"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("user data", encoding="utf-8")
    with pytest.raises(maibot_install.MaiBotInstallError):
        maibot_install.install_maibot(existing)
    assert marker.read_text(encoding="utf-8") == "user data"

    actual = tmp_path / "real"
    actual.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(maibot_install.MaiBotInstallError, match="符号链接"):
        maibot_install.install_maibot(link)
    assert list(actual.iterdir()) == []


def test_missing_uv_is_diagnostic_and_does_not_publish_install_target(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(maibot_install.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    target = tmp_path / "not-created" / "runtime"
    with pytest.raises(maibot_install.MaiBotInstallError, match="未找到 uv"):
        maibot_install.install_maibot(target)
    assert not target.exists()


def test_retry_rejects_symlink_config_and_never_calls_upstream_init(monkeypatch, tmp_path: Path):
    target = tmp_path / "runtime"
    _make_incomplete_install(target)
    external_config = tmp_path / "external-config"
    external_config.mkdir()
    (target / "config").symlink_to(external_config, target_is_directory=True)
    calls: list[list[str]] = []

    def runner(command, *, cwd, env, timeout):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return PIN
        raise AssertionError(f"unexpected command: {command}")

    _patch_installer(monkeypatch, runner)
    monkeypatch.setattr(maibot_install.maibot_aux, "RUN_DIR", tmp_path / "run")
    with pytest.raises(maibot_install.MaiBotInstallError, match="符号链接"):
        maibot_install.install_maibot(target)
    assert not any(command[:2] == ["uv", "sync"] for command in calls)
    assert not any(command[:2] == ["uv", "run"] for command in calls)
    assert list(external_config.iterdir()) == []


def test_retry_rejects_dependency_drift_without_restoring_source(monkeypatch, tmp_path: Path):
    target = tmp_path / "runtime"
    _make_incomplete_install(target)
    (target / "uv.lock").write_text("user dependency edit", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command, *, cwd, env, timeout):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return PIN
        raise AssertionError(f"unexpected command: {command}")

    _patch_installer(monkeypatch, runner)
    monkeypatch.setattr(maibot_install.maibot_aux, "RUN_DIR", tmp_path / "run")
    with pytest.raises(maibot_install.MaiBotInstallError, match="依赖文件已变更"):
        maibot_install.install_maibot(target)
    assert (target / "uv.lock").read_text(encoding="utf-8") == "user dependency edit"
    assert not any(command[:2] == ["uv", "sync"] for command in calls)


def test_running_managed_instance_blocks_incomplete_retry(monkeypatch, tmp_path: Path):
    target = tmp_path / "runtime"
    _make_incomplete_install(target)
    calls: list[list[str]] = []

    def runner(command, *, cwd, env, timeout):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return PIN
        raise AssertionError(f"unexpected command: {command}")

    _patch_installer(monkeypatch, runner)
    aux = maibot_install.maibot_aux
    monkeypatch.setattr(aux, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(aux, "PID_FILE", tmp_path / "run" / "maibot.pid")
    monkeypatch.setattr(aux, "OWNER_FILE", tmp_path / "run" / "maibot.owner.json")
    monkeypatch.setattr(aux, "read_pid_file", lambda _path: 4321)
    monkeypatch.setattr(aux, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(aux, "_read_owner", lambda: {"pid": 4321, "instance_dir": str(target)})
    monkeypatch.setattr(aux, "current_managed_process", lambda: 4321)
    monkeypatch.setattr(aux, "_has_unresolved_orphan_group", lambda: False)
    with pytest.raises(maibot_install.MaiBotInstallError, match="运行"):
        maibot_install.install_maibot(target)
    assert not any(command[:2] == ["uv", "sync"] for command in calls)
    assert _read_marker(target)["state"] == "incomplete"


def test_wrong_checkout_is_rejected_before_uv_and_owned_stage_is_cleaned(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def wrong_pin(command, *, cwd, env, timeout):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return "f" * 40
        return _successful_command(command, cwd=cwd, env=env, timeout=timeout)

    _patch_installer(monkeypatch, wrong_pin)
    target = tmp_path / "runtime"
    sibling = tmp_path / "keep.txt"
    sibling.write_text("untouched", encoding="utf-8")
    with pytest.raises(maibot_install.MaiBotInstallError, match="不匹配"):
        maibot_install.install_maibot(target)
    assert not any(command[:2] == ["uv", "sync"] for command in calls)
    assert not target.exists()
    assert not list(tmp_path.glob(".maibot-source-*"))
    assert sibling.read_text(encoding="utf-8") == "untouched"


def test_network_failure_cleans_only_owned_stage(monkeypatch, tmp_path: Path):
    sibling = tmp_path / "user-data"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")

    def fail_clone(command, *, cwd, env, timeout):
        if command[:2] == ["git", "clone"]:
            raise maibot_install.MaiBotInstallError("git clone failed")
        return _successful_command(command, cwd=cwd, env=env, timeout=timeout)

    _patch_installer(monkeypatch, fail_clone)
    target = tmp_path / "runtime"
    with pytest.raises(maibot_install.MaiBotInstallError, match="clone"):
        maibot_install.install_maibot(target)
    assert not target.exists()
    assert not list(tmp_path.glob(".maibot-source-*"))
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_sync_interruption_keeps_incomplete_source_and_retry_preserves_user_files(monkeypatch, tmp_path: Path):
    sentinel = tmp_path / "unrelated"
    sentinel.mkdir()
    (sentinel / "file").write_text("keep", encoding="utf-8")
    failed = False
    calls: list[list[str]] = []

    def interrupted_sync(command, *, cwd, env, timeout):
        nonlocal failed
        calls.append(command)
        if command[:2] == ["uv", "sync"]:
            if not failed:
                failed = True
                _successful_command(command, cwd=cwd, env=env, timeout=timeout)
                raise maibot_install.MaiBotInstallError("uv sync failed")
        return _successful_command(command, cwd=cwd, env=env, timeout=timeout)

    _patch_installer(monkeypatch, interrupted_sync)
    target = tmp_path / "runtime"
    with pytest.raises(maibot_install.MaiBotInstallError, match="incomplete"):
        maibot_install.install_maibot(target)
    assert target.is_dir()
    assert _read_marker(target)["state"] == "incomplete"

    config = target / "config"
    config.mkdir()
    user_files = {
        config / "bot_config.toml": b"user bot config",
        config / "model_config.toml": b"user model config",
        target / "eula.confirmed": b"user eula hash",
        target / "privacy.confirmed": b"user privacy hash",
    }
    for path, content in user_files.items():
        path.write_bytes(content)
    before = {path: path.read_bytes() for path in user_files}

    assert maibot_install.install_maibot(target) == target
    assert {path: path.read_bytes() for path in user_files} == before
    assert _read_marker(target)["state"] == "complete"
    assert sum(command[:2] == ["git", "clone"] for command in calls) == 1
    assert sum(command[:2] == ["uv", "sync"] for command in calls) == 2
    assert (sentinel / "file").read_text(encoding="utf-8") == "keep"


def test_init_interruption_retry_keeps_config_and_protocol_hashes(monkeypatch, tmp_path: Path):
    failed = False
    calls: list[tuple[list[str], Path]] = []

    def interrupted_init(command, *, cwd, env, timeout):
        nonlocal failed
        calls.append((command, cwd))
        if command[:2] == ["uv", "run"] and not failed:
            failed = True
            config = cwd / "config"
            config.mkdir(exist_ok=True)
            (config / "bot_config.toml").write_bytes(b"partially generated user config")
            raise maibot_install.MaiBotInstallError("MaiBot init interrupted")
        return _successful_command(command, cwd=cwd, env=env, timeout=timeout)

    _patch_installer(monkeypatch, interrupted_init)
    target = tmp_path / "runtime"
    with pytest.raises(maibot_install.MaiBotInstallError, match="incomplete"):
        maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "incomplete"
    for document, confirmation in (("EULA.md", "eula.confirmed"), ("PRIVACY.md", "privacy.confirmed")):
        content = (target / document).read_bytes()
        (target / confirmation).write_text(hashlib.md5(content).hexdigest(), encoding="utf-8")
    existing_config = target / "config" / "bot_config.toml"
    before = {
        existing_config: existing_config.read_bytes(),
        target / "EULA.md": (target / "EULA.md").read_bytes(),
        target / "PRIVACY.md": (target / "PRIVACY.md").read_bytes(),
        target / "eula.confirmed": (target / "eula.confirmed").read_bytes(),
        target / "privacy.confirmed": (target / "privacy.confirmed").read_bytes(),
    }

    assert maibot_install.install_maibot(target) == target
    assert {path: path.read_bytes() for path in before} == before
    assert (target / "config" / "model_config.toml").is_file()
    assert _read_marker(target)["state"] == "complete"
    uv_cwds = [cwd for command, cwd in calls if command[:2] in (["uv", "sync"], ["uv", "run"])]
    assert uv_cwds
    assert all(cwd == target for cwd in uv_cwds)


def test_concurrent_install_is_serialized_and_second_call_is_idempotent(monkeypatch, tmp_path: Path):
    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    def runner(command, *, cwd, env, timeout):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.01)
            return _successful_command(command, cwd=cwd, env=env, timeout=timeout)
        finally:
            with counter_lock:
                active -= 1

    _patch_installer(monkeypatch, runner)
    target = tmp_path / "runtime"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: maibot_install.install_maibot(target), range(2)))
    assert results == [target, target]
    assert max_active == 1


def test_unmarked_existing_same_pin_directory_is_not_adopted(monkeypatch, tmp_path: Path):
    target = tmp_path / "runtime"
    (target / ".git").mkdir(parents=True)
    (target / "pyproject.toml").write_text("pinned", encoding="utf-8")
    (target / "uv.lock").write_text("locked", encoding="utf-8")
    python = maibot_install.maibot_aux.default_managed_python(target)
    python.parent.mkdir(parents=True)
    (python.parent.parent / "pyvenv.cfg").write_text("version = 3.12.8\n", encoding="utf-8")
    python.write_text("", encoding="utf-8")
    config = target / "config"
    config.mkdir()
    original = {
        "bot_config.toml": "user bot config",
        "model_config.toml": "user model config",
    }
    for name, content in original.items():
        (config / name).write_text(content, encoding="utf-8")
    (target / "EULA.md").write_text("EULA", encoding="utf-8")
    (target / "PRIVACY.md").write_text("Privacy", encoding="utf-8")

    def current_pin(command, *, cwd, env, timeout):
        assert command[:2] == ["git", "rev-parse"]
        return PIN

    _patch_installer(monkeypatch, current_pin)
    with pytest.raises(maibot_install.MaiBotInstallError, match="未知|标记"):
        maibot_install.install_maibot(target)
    assert {name: (config / name).read_text(encoding="utf-8") for name in original} == original


def test_subprocess_diagnostics_never_echo_environment_or_tool_output(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(maibot_install.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setenv("MAIBOT_API_KEY", "secret-value")
    monkeypatch.setattr(
        maibot_install.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="MAIBOT_API_KEY=secret-value", stderr="uv failed with secret-value"
        ),
    )
    rc = main(["maibot", "install", "--dir", str(tmp_path / "runtime")])
    assert rc == 1
    output = capsys.readouterr()
    assert "secret-value" not in output.out + output.err
    assert "MAIBOT_API_KEY" not in output.out + output.err


def test_subprocess_timeout_has_safe_diagnostic(monkeypatch, tmp_path: Path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="secret-value")

    monkeypatch.setattr(maibot_install.subprocess, "run", timeout)
    with pytest.raises(maibot_install.MaiBotInstallError, match="超时") as error:
        maibot_install.run_command(
            ["uv", "sync", "--frozen", "--no-dev"],
            cwd=tmp_path,
            env={},
            timeout=1,
        )
    assert "secret-value" not in str(error.value)


def test_terms_and_accept_use_current_protocol_hashes_only_after_both_flags(monkeypatch, tmp_path: Path, capsys):
    _set_managed_dir(monkeypatch, tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "EULA.md").write_text("EULA v1", encoding="utf-8")
    (tmp_path / "PRIVACY.md").write_text("Privacy v1", encoding="utf-8")
    monkeypatch.setattr(maibot_install, "run_command", lambda *args, **kwargs: PIN)

    assert main(["maibot", "terms"]) == 0
    shown = capsys.readouterr().out
    assert "EULA v1" in shown
    assert "Privacy v1" in shown
    assert not (tmp_path / "eula.confirmed").exists()
    assert not (tmp_path / "privacy.confirmed").exists()

    with pytest.raises(SystemExit):
        main(["maibot", "accept", "--eula"])
    assert not (tmp_path / "eula.confirmed").exists()

    assert main(["maibot", "accept", "--eula", "--privacy"]) == 0
    assert (tmp_path / "eula.confirmed").read_text(encoding="utf-8") == hashlib.md5(b"EULA v1").hexdigest()
    assert (tmp_path / "privacy.confirmed").read_text(encoding="utf-8") == hashlib.md5(b"Privacy v1").hexdigest()
    assert maibot_install.protocol_problems(tmp_path) == []

    (tmp_path / "EULA.md").write_text("EULA v2", encoding="utf-8")
    assert any("协议已变更" in issue for issue in maibot_install.protocol_problems(tmp_path))


def test_status_is_read_only_and_uses_configured_directory(monkeypatch, tmp_path: Path, capsys):
    target = tmp_path / "custom managed instance"
    _make_incomplete_install(target)
    python = target / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    (target / ".venv" / "pyvenv.cfg").write_text("version = 3.12.8\n", encoding="utf-8")
    (target / "config").mkdir()
    (target / "config" / "bot_config.toml").write_text("user config", encoding="utf-8")
    (target / maibot_install.INSTALL_MARKER_NAME).write_text(
        json.dumps({
            "pin": PIN,
            "state": "incomplete",
            "dependency_hash": maibot_install.dependency_hash(target),
        }),
        encoding="utf-8",
    )
    before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    _set_managed_dir(monkeypatch, target)
    monkeypatch.setattr(maibot_install, "run_command", lambda *args, **kwargs: PIN)
    monkeypatch.setattr(maibot_install.maibot_aux, "managed_runtime_state", lambda: "off")

    assert main(["maibot", "status"]) == 0
    status = capsys.readouterr().out
    assert str(target) in status
    assert PIN in status
    assert "3.12.8" in status
    assert "incomplete" in status
    assert "托管：未开启" in status
    after = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert after == before
    assert not (target / "eula.confirmed").exists()


def test_managed_preflight_blocks_owned_incomplete_but_keeps_manual_instance_legacy(monkeypatch, tmp_path: Path):
    target = tmp_path / "instance"
    (target / "config").mkdir(parents=True)
    (target / "bot.py").write_text("", encoding="utf-8")
    (target / "config" / "bot_config.toml").write_text(
        '[maim_message]\nws_server_host = "127.0.0.1"\nws_server_port = 8000\nauth_token = "bridge-token"\n',
        encoding="utf-8",
    )
    (target / "config" / "model_config.toml").write_text("[models]\n", encoding="utf-8")
    (target / "EULA.md").write_text("EULA", encoding="utf-8")
    (target / "PRIVACY.md").write_text("Privacy", encoding="utf-8")
    (target / "eula.confirmed").write_text(hashlib.md5(b"EULA").hexdigest(), encoding="utf-8")
    (target / "privacy.confirmed").write_text(hashlib.md5(b"Privacy").hexdigest(), encoding="utf-8")
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    config = maibot_install.maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=target, python=python)
    bridge_config = MaiBotBridgeConfig(
        enabled=True,
        url="ws://127.0.0.1:8000/ws",
        bot_id=10001,
        group_ids=frozenset({700001}),
        platform="pallas-qq",
        token="bridge-token",
    )
    marker = target / maibot_install.INSTALL_MARKER_NAME
    marker.write_text(json.dumps({"pin": PIN, "state": "incomplete", "dependency_hash": "a" * 64}), encoding="utf-8")
    monkeypatch.setattr(maibot_install.maibot_aux, "_effective_config_ready", lambda _instance: True)
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda _root: True)
    problems = maibot_install.maibot_aux.validate_managed_instance(config, bridge_config)
    assert any("安装未完成" in problem for problem in problems)
    assert any("兼容补丁" in problem for problem in problems)

    marker.unlink()
    _make_compat_sources(target)
    native_compat.apply_native_compat(target)
    maibot_install.maibot_assets.deploy_assets(target)
    assert maibot_install.maibot_aux.validate_managed_instance(config, bridge_config) == []


def test_fresh_install_patches_and_builds_dashboard_before_complete(monkeypatch, tmp_path: Path):
    _patch_installer(monkeypatch)
    events: list[str] = []
    dashboard_state = {"value": "original"}

    def apply(root: Path, *, expected_pin: str) -> str:
        assert expected_pin == PIN
        assert _read_marker(root)["state"] == "incomplete"
        events.append("patch")
        dashboard_state["value"] = "patched"
        return "patched"

    def build(root: Path) -> None:
        assert dashboard_state["value"] == "patched"
        assert _read_marker(root)["state"] == "incomplete"
        events.append("build")
        dashboard_state["value"] = "built"

    monkeypatch.setattr(maibot_dashboard, "dashboard_state", lambda _root: dashboard_state["value"])
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda _root: dashboard_state["value"] == "built")
    monkeypatch.setattr(maibot_dashboard, "apply_dashboard_compat", apply)
    monkeypatch.setattr(maibot_dashboard, "build_dashboard", build)

    target = tmp_path / "fresh"
    maibot_install.install_maibot(target)
    assert events == ["patch", "build"]
    assert _read_marker(target)["state"] == "complete"


def test_complete_install_without_built_frontend_upgrades_only_managed_target(monkeypatch, tmp_path: Path):
    _patch_installer(monkeypatch)
    target = tmp_path / "existing-managed"
    maibot_install.install_maibot(target)
    current = {"state": "original"}
    calls: list[str] = []

    def apply(root: Path, *, expected_pin: str) -> str:
        assert expected_pin == PIN
        assert _read_marker(root)["state"] == "incomplete"
        calls.append("patch")
        current["state"] = "patched"
        return "patched"

    def build(root: Path) -> None:
        assert _read_marker(root)["state"] == "incomplete"
        assert current["state"] == "patched"
        calls.append("build")
        current["state"] = "built"

    def state(root: Path) -> str:
        return current["state"]

    monkeypatch.setattr(maibot_dashboard, "dashboard_state", state)
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda root: state(root) == "built")
    monkeypatch.setattr(maibot_dashboard, "apply_dashboard_compat", apply)
    monkeypatch.setattr(maibot_dashboard, "build_dashboard", build)

    assert "前端缺失或待构建" in maibot_install.installation_status(target)

    maibot_install.install_maibot(target)
    assert calls == ["patch", "build"]
    assert _read_marker(target)["state"] == "complete"


def test_failed_frontend_build_never_marks_fresh_install_complete(monkeypatch, tmp_path: Path):
    _patch_installer(monkeypatch)
    dashboard_state = {"value": "original"}

    def apply(_root: Path, *, expected_pin: str) -> str:
        assert expected_pin == PIN
        dashboard_state["value"] = "patched"
        return "patched"

    def fail_build(_root: Path) -> None:
        raise maibot_dashboard.DashboardCompatError("browser build failed")

    monkeypatch.setattr(maibot_dashboard, "dashboard_state", lambda _root: dashboard_state["value"])
    monkeypatch.setattr(maibot_dashboard, "validate_dashboard_build", lambda _root: dashboard_state["value"] == "built")
    monkeypatch.setattr(maibot_dashboard, "apply_dashboard_compat", apply)
    monkeypatch.setattr(maibot_dashboard, "build_dashboard", fail_build)

    target = tmp_path / "fresh-build-failure"
    with pytest.raises(maibot_install.MaiBotInstallError, match="incomplete"):
        maibot_install.install_maibot(target)
    assert _read_marker(target)["state"] == "incomplete"
