"""Install and verify the packaged Pallas provider plugin for MaiBot."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path

ASSET_PACKAGE = "pallas.product.agent_bridge.maibot_plugin"
PLUGIN_ID = "pallas.maibot_managed_provider"
PLUGIN_DIR_NAME = "pallas-managed-provider"
MARKER_NAME = ".pallas-managed-assets.json"
MARKER_SCHEMA = 1
SDK_VERSION = "2.16.0"
HOST_VERSION = "1.3.15"
ASSET_NAMES = ("_manifest.json", "plugin.py")


class MaiBotAssetsError(RuntimeError):
    """MaiBot plugin assets are missing, changed, or unsafe to replace."""


def _resource_assets() -> dict[str, bytes]:
    try:
        root = files(ASSET_PACKAGE)
        assets = {name: root.joinpath(name).read_bytes() for name in ASSET_NAMES}
        manifest = json.loads(assets["_manifest.json"])
    except (OSError, ModuleNotFoundError, TypeError, ValueError):
        raise MaiBotAssetsError("Pallas 托管插件资产缺失或无效") from None
    if (
        not isinstance(manifest, dict)
        or manifest.get("id") != PLUGIN_ID
        or type(manifest.get("manifest_version")) is not int
        or manifest["manifest_version"] != 2
        or manifest.get("sdk") != {"min_version": SDK_VERSION, "max_version": SDK_VERSION}
        or manifest.get("host_application") != {"min_version": HOST_VERSION, "max_version": HOST_VERSION}
    ):
        raise MaiBotAssetsError("Pallas 托管插件资产身份无效")
    return assets


def _assert_no_symlinks(path: Path) -> None:
    path = path.absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise MaiBotAssetsError("MaiBot 插件路径包含符号链接，拒绝操作")


def _hashes(assets: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in assets.items()}


def _managed_target_state(target: Path) -> str:
    if not target.exists():
        return "missing"
    if target.is_symlink() or not target.is_dir():
        raise MaiBotAssetsError("MaiBot 插件目标不是安全目录")
    marker_path = target / MARKER_NAME
    if marker_path.is_symlink() or not marker_path.is_file():
        raise MaiBotAssetsError("MaiBot 插件目录未受 Pallas 管理，拒绝覆盖")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise MaiBotAssetsError("MaiBot 插件管理标记无效") from None
    hashes = marker.get("files") if isinstance(marker, dict) else None
    if (
        not isinstance(marker, dict)
        or set(marker) != {"schema", "plugin_id", "files"}
        or type(marker.get("schema")) is not int
        or marker["schema"] != MARKER_SCHEMA
        or marker.get("plugin_id") != PLUGIN_ID
        or not isinstance(hashes, dict)
        or set(hashes) != set(ASSET_NAMES)
        or any(not isinstance(value, str) or len(value) != 64 for value in hashes.values())
    ):
        raise MaiBotAssetsError("MaiBot 插件管理标记无效")
    names = {entry.name for entry in target.iterdir()}
    if names - {*ASSET_NAMES, MARKER_NAME}:
        raise MaiBotAssetsError("MaiBot 插件目录包含未知文件，拒绝覆盖")
    if {*ASSET_NAMES, MARKER_NAME} - names:
        raise MaiBotAssetsError("MaiBot 插件文件缺失，拒绝覆盖")
    actual: dict[str, str] = {}
    for name in ASSET_NAMES:
        path = target / name
        if path.is_symlink() or not path.is_file():
            raise MaiBotAssetsError("MaiBot 插件文件缺失或不是普通文件")
        try:
            actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            raise MaiBotAssetsError("无法读取 MaiBot 插件文件") from None
    if actual != hashes:
        raise MaiBotAssetsError("MaiBot 插件文件已被外部修改，拒绝覆盖")
    try:
        manifest = json.loads((target / "_manifest.json").read_bytes())
    except (OSError, ValueError):
        raise MaiBotAssetsError("MaiBot 插件清单无效") from None
    if not isinstance(manifest, dict) or manifest.get("id") != PLUGIN_ID:
        raise MaiBotAssetsError("MaiBot 插件身份与 Pallas 托管插件不符")
    return "current" if actual == _hashes(_resource_assets()) else "outdated"


def _reject_duplicate_plugin_id(plugins_dir: Path, target: Path) -> None:
    if not plugins_dir.exists():
        return
    if plugins_dir.is_symlink() or not plugins_dir.is_dir():
        raise MaiBotAssetsError("MaiBot plugins 路径不是安全目录")
    for candidate in plugins_dir.iterdir():
        if candidate == target or not candidate.is_dir():
            continue
        if candidate.is_symlink():
            raise MaiBotAssetsError("MaiBot plugins 中存在无法安全检查的符号链接")
        manifest_path = candidate / "_manifest.json"
        if manifest_path.is_symlink():
            raise MaiBotAssetsError("MaiBot 插件清单是符号链接，无法核实插件身份")
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_bytes())
        except (OSError, ValueError):
            raise MaiBotAssetsError("MaiBot 已有插件身份无法核实，拒绝部署") from None
        if isinstance(manifest, dict) and manifest.get("id") == PLUGIN_ID:
            raise MaiBotAssetsError("MaiBot 中已存在同 ID 插件，拒绝部署")


def inspect_assets(instance_dir: Path) -> str:
    """Return missing/current/outdated; reject unmanaged or tampered targets."""
    plugins_dir = instance_dir / "plugins"
    target = plugins_dir / PLUGIN_DIR_NAME
    try:
        _assert_no_symlinks(target)
        _reject_duplicate_plugin_id(plugins_dir, target)
        return _managed_target_state(target)
    except OSError:
        raise MaiBotAssetsError("无法安全核实 MaiBot 插件资产") from None


def retire_managed_provider_assets(instance_dir: Path) -> Path | None:
    """停机、迁移及最终模型校验后，由持有实例管理锁的 caller 归档旧代理。"""
    if inspect_assets(instance_dir) == "missing":
        return None
    target = instance_dir / "plugins" / PLUGIN_DIR_NAME
    archive: Path | None = None
    try:
        _assert_no_symlinks(instance_dir)
        archive = Path(tempfile.mkdtemp(prefix=".pallas-retired-provider-", dir=instance_dir))
        _assert_no_symlinks(archive)
        destination = archive / PLUGIN_DIR_NAME
        target.rename(destination)
        return destination
    except OSError:
        if archive is not None:
            try:
                archive.rmdir()
            except OSError:
                pass
        raise MaiBotAssetsError("旧 MaiBot Provider 代理归档失败，未确认退出插件扫描目录") from None


def _stage_assets(plugins_dir: Path, assets: dict[str, bytes]) -> Path:
    try:
        stage = Path(tempfile.mkdtemp(prefix=".pallas-maibot-assets-stage-", dir=plugins_dir))
    except OSError:
        raise MaiBotAssetsError("无法创建 MaiBot 插件暂存目录") from None
    try:
        for name, content in assets.items():
            path = stage / name
            path.write_bytes(content)
            path.chmod(0o644)
        marker = {
            "schema": MARKER_SCHEMA,
            "plugin_id": PLUGIN_ID,
            "files": _hashes(assets),
        }
        marker_path = stage / MARKER_NAME
        marker_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
        marker_path.chmod(0o600)
    except OSError:
        shutil.rmtree(stage, ignore_errors=True)
        raise MaiBotAssetsError("无法写入 MaiBot 插件暂存文件") from None
    return stage


def _publish_assets(stage: Path, backup_parent: Path, target: Path) -> None:
    backup: Path | None = None
    _assert_no_symlinks(backup_parent)
    _assert_no_symlinks(target)
    if target.exists():
        try:
            backup = Path(tempfile.mkdtemp(prefix=".pallas-maibot-assets-backup-", dir=backup_parent))
            backup.rmdir()
            target.rename(backup)
        except OSError:
            if backup is not None and backup.exists():
                if not target.exists():
                    raise MaiBotAssetsError(f"备份原 MaiBot 插件资产时回滚不完整；备份保留于 [{backup}]") from None
                try:
                    backup.rmdir()
                except OSError:
                    raise MaiBotAssetsError(
                        f"无法安全备份原 MaiBot 插件资产，原目录未变更；临时目录保留于 [{backup}]"
                    ) from None
            raise MaiBotAssetsError("无法安全备份原 MaiBot 插件资产，原目录未变更") from None
        try:
            stage.rename(target)
        except OSError:
            try:
                backup.rename(target)
            except OSError:
                raise MaiBotAssetsError(f"插件资产发布失败，回滚不完整；备份保留于 [{backup}]") from None
            else:
                raise MaiBotAssetsError("插件资产发布失败，原受管目录已恢复") from None
    else:
        try:
            stage.rename(target)
        except OSError:
            raise MaiBotAssetsError("插件资产发布失败，未发布新目录") from None
    if backup is not None:
        try:
            shutil.rmtree(backup)
        except OSError:
            if backup.exists():
                raise MaiBotAssetsError(f"新插件资产已发布，但旧备份清理失败；备份保留于 [{backup}]") from None
            raise MaiBotAssetsError("新插件资产已发布，但旧备份清理报告失败；备份目录已消失") from None


def deploy_assets(instance_dir: Path) -> None:
    """Atomically install packaged assets, replacing only a verified managed copy."""
    plugins_dir = instance_dir / "plugins"
    target = plugins_dir / PLUGIN_DIR_NAME
    try:
        _assert_no_symlinks(target)
        _reject_duplicate_plugin_id(plugins_dir, target)
        if _managed_target_state(target) == "current":
            return
        assets = _resource_assets()
    except OSError:
        raise MaiBotAssetsError("无法安全核实 MaiBot 插件资产") from None
    try:
        plugins_dir.mkdir(parents=True, exist_ok=True)
        _assert_no_symlinks(target)
        stage = _stage_assets(plugins_dir, assets)
    except OSError:
        raise MaiBotAssetsError("无法创建 MaiBot 插件暂存目录") from None
    try:
        _publish_assets(stage, plugins_dir.parent, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
