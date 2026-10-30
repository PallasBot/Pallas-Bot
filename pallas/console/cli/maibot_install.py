"""Install and inspect the pinned, isolated MaiBot source runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from pallas.console.cli import maibot_assets, maibot_aux, maibot_dashboard
from pallas.console.cli.process_util import env_for_nested_project, is_windows
from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import DATA_ROOT, PROJECT_ROOT
from pallas.product.agent_bridge.native_compat import NativeCompatError, apply_native_compat, native_compat_state

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractContextManager

UPSTREAM_URL = "https://github.com/MaiM-with-u/MaiBot.git"
PINNED_REVISION = maibot_aux.MANAGED_INSTALL_PIN
INSTALL_MARKER_NAME = maibot_aux.MANAGED_INSTALL_MARKER
MANAGED_DIR_KEY = maibot_aux.MANAGED_DIR_KEY
MANAGED_PYTHON_KEY = maibot_aux.MANAGED_PYTHON_KEY
GIT_TIMEOUT_S = 600.0
UV_SYNC_TIMEOUT_S = 1800.0
UV_INIT_TIMEOUT_S = 120.0


class MaiBotInstallError(RuntimeError):
    """Safe-to-display installation or protocol-management error."""


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))  # noqa: PTH100 — retain symlinks for explicit safety checks


def configured_maibot_dir() -> Path | None:
    raw = str(repo_env_raw_value(MANAGED_DIR_KEY) or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser()
        if "\x00" in raw:
            raise ValueError
        return _absolute_path(path if path.is_absolute() else PROJECT_ROOT / path)
    except (OSError, RuntimeError, ValueError):
        raise MaiBotInstallError(f"{MANAGED_DIR_KEY} 路径无效") from None


def default_maibot_dir() -> Path:
    return _absolute_path(DATA_ROOT / "runtimes" / "maibot")


def selected_maibot_dir(explicit: Path | None = None) -> Path:
    configured = configured_maibot_dir()
    if explicit is not None:
        target = _absolute_path(explicit if explicit.is_absolute() else Path.cwd() / explicit)
        if configured is not None and target != configured:
            raise MaiBotInstallError(f"--dir 与已配置的 {MANAGED_DIR_KEY} 不一致；请先统一安装目录与托管配置")
        return target
    return configured or default_maibot_dir()


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                raise MaiBotInstallError(f"路径包含符号链接，拒绝操作：{current}")
    except ValueError:
        raise MaiBotInstallError("安装路径无效") from None


def _lock_path(target: Path) -> Path:
    return target.parent / f".{target.name}.maibot-install.lock"


def _target_lock(target: Path) -> AbstractContextManager[None]:
    lock = _lock_path(target)
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        raise MaiBotInstallError("安装锁路径不是安全的普通文件")
    return interprocess_file_lock(lock)


def _command_label(command: Sequence[str]) -> str:
    if command[:2] == ["git", "clone"]:
        return "git clone"
    if command[:2] == ["git", "checkout"]:
        return "git checkout"
    if command[:2] == ["git", "rev-parse"]:
        return "git 读取版本"
    if command[:2] == ["uv", "sync"]:
        return "uv sync"
    if command[:2] == ["uv", "run"]:
        return "MaiBot 配置初始化"
    return "子进程命令"


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> str:
    """Run quietly; child output may contain credentials and is never surfaced."""
    label = _command_label(command)
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise MaiBotInstallError(f"未找到所需命令：{command[0]}") from None
    except subprocess.TimeoutExpired:
        raise MaiBotInstallError(f"{label} 超时") from None
    except OSError:
        raise MaiBotInstallError(f"无法执行 {label}（系统 IO 错误）") from None
    if result.returncode:
        raise MaiBotInstallError(f"{label} 失败（退出码 {result.returncode}）")
    return (result.stdout or "").strip()


def _read_revision(root: Path) -> str:
    if not (root / ".git").exists():
        raise MaiBotInstallError("目标不是 MaiBot Git 源码目录")
    revision = run_command(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        env=env_for_nested_project(),
        timeout=GIT_TIMEOUT_S,
    ).lower()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise MaiBotInstallError("无法安全读取 MaiBot 完整源码版本")
    return revision


def dependency_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise MaiBotInstallError(f"关键依赖文件缺失或是符号链接：{name}")
        try:
            content = path.read_bytes()
        except OSError:
            raise MaiBotInstallError(f"无法读取关键依赖文件：{name}") from None
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _read_install_marker(root: Path) -> dict[str, str] | None:
    marker_path = root / INSTALL_MARKER_NAME
    if marker_path.is_symlink():
        raise MaiBotInstallError("MaiBot CLI 安装标记是符号链接，拒绝操作")
    if not marker_path.exists():
        return None
    if not marker_path.is_file():
        raise MaiBotInstallError("MaiBot CLI 安装标记不是普通文件")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise MaiBotInstallError("MaiBot CLI 安装标记无效") from None
    if (
        not isinstance(marker, dict)
        or set(marker) != {"pin", "state", "dependency_hash"}
        or marker.get("pin") != PINNED_REVISION
        or not isinstance(marker.get("state"), str)
        or marker.get("state") not in {"incomplete", "complete"}
        or not isinstance(marker.get("dependency_hash"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", marker["dependency_hash"])
    ):
        raise MaiBotInstallError("MaiBot CLI 安装标记无效")
    return marker


def _write_install_marker(root: Path, *, state: str, dependencies: str) -> None:
    marker_path = root / INSTALL_MARKER_NAME
    if marker_path.is_symlink():
        raise MaiBotInstallError("MaiBot CLI 安装标记是符号链接，拒绝写入")
    marker = {"pin": PINNED_REVISION, "state": state, "dependency_hash": dependencies}
    atomic_write_text(marker_path, json.dumps(marker, ensure_ascii=False, sort_keys=True))


def installation_status(root: Path) -> str:
    if not root.is_dir():
        return "未安装"
    try:
        marker = _read_install_marker(root)
        if marker is None:
            return "手工实例（无 CLI 安装标记）"
        if dependency_hash(root) != marker["dependency_hash"]:
            return "CLI 标记存在，但关键依赖文件已变更"
        try:
            assets = maibot_assets.inspect_assets(root)
        except maibot_assets.MaiBotAssetsError as exc:
            if "文件缺失" in str(exc):
                return f"MaiBot 插件资产缺失：{exc}"
            return f"MaiBot 插件资产无效：{exc}"
        try:
            dashboard = maibot_dashboard.dashboard_state(root)
        except maibot_dashboard.DashboardCompatError as exc:
            return f"MaiBot 前端无效：{exc}"
        if dashboard == "missing":
            return f"CLI 管理，{marker['state']}；MaiBot dashboard 源码缺失"
        if dashboard != "built":
            tool_problem = maibot_dashboard.build_tools_error()
            detail = f"（{tool_problem}）" if tool_problem else ""
            return f"CLI 管理，{marker['state']}；MaiBot 前端缺失或待构建{detail}"
        if marker["state"] == "complete" and not _is_complete_install(root):
            return "CLI 完成标记与实际运行环境不一致"
        legacy_note = "；旧 Provider 代理待模型迁移后归档" if assets != "missing" else ""
        return f"CLI 管理，{marker['state']}{legacy_note}"
    except MaiBotInstallError:
        return "CLI 安装标记或关键依赖无效"


def protocol_problems(instance_dir: Path) -> list[str]:
    """Use the exact confirmation-file format enforced by managed startup."""
    return maibot_aux._protocol_problems(instance_dir)


def _python_path(instance_dir: Path) -> Path:
    configured = str(repo_env_raw_value(MANAGED_PYTHON_KEY) or "").strip()
    if configured:
        try:
            python = Path(configured).expanduser()
            if "\x00" in configured:
                raise ValueError
            return _absolute_path(python if python.is_absolute() else PROJECT_ROOT / python)
        except (OSError, RuntimeError, ValueError):
            raise MaiBotInstallError(f"{MANAGED_PYTHON_KEY} 路径无效") from None
    return maibot_aux.default_managed_python(instance_dir)


def _python_version(python: Path, instance_dir: Path) -> str:
    candidates = [instance_dir / ".venv" / "pyvenv.cfg", python.parent.parent / "pyvenv.cfg"]
    for config in dict.fromkeys(candidates):
        try:
            text = config.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        match = re.search(r"(?m)^version\s*=\s*([^\s]+)", text)
        if match and re.fullmatch(r"(?:\d+\.){1,2}\d+[a-zA-Z0-9.+-]*", match.group(1)):
            return match.group(1)
    return "未知"


def _console_script_path(root: Path) -> Path:
    folder = "Scripts" if is_windows() else "bin"
    suffix = ".exe" if is_windows() else ""
    return root / ".venv" / folder / f"maibot{suffix}"


def _is_complete_install(
    root: Path,
    *,
    verify_assets: bool = True,
    verify_dashboard: bool = True,
    allow_native_compat_upgrade: bool = False,
) -> bool:
    python = maibot_aux.default_managed_python(root)
    required = (
        root / "bot.py",
        root / "pyproject.toml",
        root / "uv.lock",
        root / "EULA.md",
        root / "PRIVACY.md",
        root / "config" / "bot_config.toml",
        root / "config" / "model_config.toml",
        python,
        python.parent.parent / "pyvenv.cfg",
        _console_script_path(root),
    )
    if not all(path.is_file() for path in required) or not (root / ".git").is_dir():
        return False
    try:
        compat_state = native_compat_state(root, expected_pin=PINNED_REVISION)
        if compat_state != "patched" and not (allow_native_compat_upgrade and compat_state == "upgradeable"):
            return False
    except (NativeCompatError, OSError):
        return False
    if verify_assets:
        try:
            maibot_assets.inspect_assets(root)
        except maibot_assets.MaiBotAssetsError:
            return False
    if verify_dashboard:
        try:
            if not maibot_dashboard.validate_dashboard_build(root):
                return False
        except maibot_dashboard.DashboardCompatError:
            return False
    if not is_windows():
        try:
            shebang = _console_script_path(root).read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError, UnicodeDecodeError):
            return False
        if shebang != f"#!{python}":
            return False
    return True


def _assert_installer_paths_safe(root: Path) -> None:
    paths = (
        root / ".git",
        root / "pyproject.toml",
        root / "uv.lock",
        root / ".venv",
        root / INSTALL_MARKER_NAME,
        root / "config",
        root / "config" / "bot_config.toml",
        root / "config" / "model_config.toml",
        root / "EULA.md",
        root / "PRIVACY.md",
        root / "eula.confirmed",
        root / "privacy.confirmed",
    )
    for path in paths:
        if path.is_symlink():
            raise MaiBotInstallError(f"安装文件是符号链接，拒绝操作：{path.name}")
    config_dir = root / "config"
    if config_dir.exists() and not config_dir.is_dir():
        raise MaiBotInstallError("config 不是目录，拒绝初始化配置")
    for name in ("bot_config.toml", "model_config.toml"):
        path = config_dir / name
        if path.exists() and not path.is_file():
            raise MaiBotInstallError(f"MaiBot 配置不是普通文件：{name}")


def _prepare_parent(target: Path) -> None:
    _assert_no_symlink_components(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise MaiBotInstallError("无法创建安装目录的父目录") from None
    _assert_no_symlink_components(target)


def _validate_existing_target(target: Path) -> str:
    """Return the managed target state; unknown directories are never adopted."""
    _assert_no_symlink_components(target)
    if not target.exists():
        return "new"
    if not target.is_dir():
        raise MaiBotInstallError("安装目标已存在且不是目录，拒绝覆盖")
    if not any(target.iterdir()):
        return "new"
    marker = _read_install_marker(target)
    if marker is None:
        raise MaiBotInstallError("安装目标包含未知文件且没有本 CLI 标记，拒绝接管")
    if not (target / ".git").is_dir():
        raise MaiBotInstallError("受管安装缺少 Git 源码目录，拒绝恢复")
    if _read_revision(target) != PINNED_REVISION:
        raise MaiBotInstallError("安装目标不是固定支持的 MaiBot 版本，拒绝恢复")
    if dependency_hash(target) != marker["dependency_hash"]:
        raise MaiBotInstallError("关键依赖文件已变更，拒绝恢复；不会还原源文件")
    _assert_installer_paths_safe(target)
    if marker["state"] == "complete":
        try:
            maibot_assets.inspect_assets(target)
        except maibot_assets.MaiBotAssetsError as exc:
            raise MaiBotInstallError(f"MaiBot 插件资产无效，拒绝恢复：{exc}") from None
        if not _is_complete_install(
            target,
            verify_assets=False,
            verify_dashboard=False,
            allow_native_compat_upgrade=True,
        ):
            raise MaiBotInstallError("完成标记与实际运行环境不一致，拒绝自动修复")
        try:
            compat_upgrade = native_compat_state(target, expected_pin=PINNED_REVISION) == "upgradeable"
        except (NativeCompatError, OSError):
            raise MaiBotInstallError("完成标记与实际运行环境不一致，拒绝自动修复") from None
        try:
            dashboard = maibot_dashboard.dashboard_state(target)
        except maibot_dashboard.DashboardCompatError as exc:
            raise MaiBotInstallError(f"MaiBot 前端无效，拒绝自动修复：{exc}") from None
        if dashboard == "missing":
            raise MaiBotInstallError("MaiBot dashboard 源码缺失，拒绝自动恢复")
        if compat_upgrade:
            return "compat-upgrade"
        if dashboard != "built":
            return "dashboard-upgrade"
        return "complete"
    try:
        maibot_assets.inspect_assets(target)
    except maibot_assets.MaiBotAssetsError as exc:
        raise MaiBotInstallError(f"MaiBot 插件资产无效，拒绝恢复：{exc}") from None
    try:
        maibot_dashboard.dashboard_state(target)
    except maibot_dashboard.DashboardCompatError as exc:
        raise MaiBotInstallError(f"MaiBot 前端无效，拒绝恢复：{exc}") from None
    return "incomplete"


def _initialize_configs(root: Path, env: Mapping[str, str]) -> None:
    # This pinned upstream release has no checked-in TOML templates; its init command
    # generates the two defaults and preserves any config file that already exists.
    _assert_installer_paths_safe(root)
    run_command(
        [
            "uv",
            "run",
            "--frozen",
            "--no-dev",
            "--no-sync",
            "--project",
            str(root),
            "maibot",
            "init",
            "--directory",
            str(root),
        ],
        cwd=root,
        env=env,
        timeout=UV_INIT_TIMEOUT_S,
    )
    for name in ("bot_config.toml", "model_config.toml"):
        config = root / "config" / name
        if not config.is_file() or config.is_symlink():
            raise MaiBotInstallError(f"MaiBot 初始化未生成有效配置文件：{name}")
    _assert_installer_paths_safe(root)


def _publish_source(stage: Path, target: Path) -> None:
    _assert_no_symlink_components(target)
    removed_empty_target = False
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise MaiBotInstallError("安装期间目标目录出现文件，拒绝覆盖")
        target.rmdir()
        removed_empty_target = True
    try:
        stage.rename(target)
    except OSError:
        if removed_empty_target and not target.exists():
            try:
                target.mkdir()
            except OSError:
                pass
        raise MaiBotInstallError("无法原子发布 MaiBot 安装目录") from None


def _clone_and_publish_source(target: Path, env: Mapping[str, str]) -> str:
    stage: Path | None = Path(tempfile.mkdtemp(prefix=".maibot-source-", dir=target.parent))
    try:
        assert stage is not None
        run_command(
            ["git", "clone", "--no-checkout", UPSTREAM_URL, str(stage)],
            cwd=target.parent,
            env=env,
            timeout=GIT_TIMEOUT_S,
        )
        run_command(
            ["git", "checkout", "--detach", PINNED_REVISION],
            cwd=stage,
            env=env,
            timeout=GIT_TIMEOUT_S,
        )
        if _read_revision(stage) != PINNED_REVISION:
            raise MaiBotInstallError("MaiBot checkout SHA 与固定支持版本不匹配，已拒绝安装")
        if not (stage / "LICENSE").is_file():
            raise MaiBotInstallError("固定版本源码缺少许可证文件，已拒绝安装")
        if (stage / ".venv").exists() or (stage / ".venv").is_symlink():
            raise MaiBotInstallError("源码暂存目录意外包含虚拟环境，拒绝发布")
        _assert_installer_paths_safe(stage)
        dependencies = dependency_hash(stage)
        _write_install_marker(stage, state="incomplete", dependencies=dependencies)
        _publish_source(stage, target)
        stage = None
        return dependencies
    finally:
        if stage is not None and stage.exists():
            try:
                shutil.rmtree(stage)
            except OSError:
                pass


def _owner_matches_target(owner: dict | None, target: Path) -> bool:
    if owner is None or not owner.get("instance_dir"):
        return True
    try:
        return Path(str(owner.get("instance_dir") or "")).resolve() == target.resolve()
    except (OSError, RuntimeError, ValueError):
        return True


def _managed_instance_running(target: Path) -> bool:
    pid = maibot_aux.read_pid_file(maibot_aux.PID_FILE)
    owner = maibot_aux._read_owner()
    if pid is not None and maibot_aux.pid_alive(pid):
        if owner is None or owner.get("pid") != pid or maibot_aux.current_managed_process() != pid:
            return True
        return _owner_matches_target(owner, target)
    if maibot_aux._has_unresolved_orphan_group():
        return owner is None or _owner_matches_target(owner, target)
    return False


def install_maibot(explicit: Path | None = None) -> Path:
    target = selected_maibot_dir(explicit)
    if shutil.which("git") is None:
        raise MaiBotInstallError("未找到 git，无法安装 MaiBot")

    _prepare_parent(target)

    with _target_lock(target), interprocess_file_lock(maibot_aux._lock_path()):
        state = _validate_existing_target(target)
        if state == "complete":
            print(f"MaiBot 已安装固定版本 {PINNED_REVISION[:12]}：{target}")
            print("现有配置未改写；统一启停请使用 Pallas 的 run/stop/restart。")
            return target
        if _managed_instance_running(target):
            raise MaiBotInstallError("MaiBot 实例正在运行或进程组身份无法核实，拒绝修改")
        if shutil.which("uv") is None:
            raise MaiBotInstallError("未找到 uv，无法安装 MaiBot 依赖")

        env = env_for_nested_project()
        if state == "new":
            dependencies = _clone_and_publish_source(target, env)
        else:
            marker = _read_install_marker(target)
            if marker is None:
                raise MaiBotInstallError("缺少本 CLI 安装标记，拒绝恢复")
            dependencies = marker["dependency_hash"]

        try:
            if state in {"dashboard-upgrade", "compat-upgrade"}:
                _write_install_marker(target, state="incomplete", dependencies=dependencies)
            _assert_installer_paths_safe(target)
            if dependency_hash(target) != dependencies:
                raise MaiBotInstallError("关键依赖文件已变更，拒绝继续安装")
            run_command(
                ["uv", "sync", "--frozen", "--no-dev"],
                cwd=target,
                env=env,
                timeout=UV_SYNC_TIMEOUT_S,
            )
            if dependency_hash(target) != dependencies:
                raise MaiBotInstallError("uv sync 后关键依赖文件发生变化，拒绝完成安装")
            _initialize_configs(target, env)
            try:
                apply_native_compat(target, expected_pin=PINNED_REVISION)
            except NativeCompatError:
                raise MaiBotInstallError("提及与启动兼容补丁校验失败，拒绝标记安装完成") from None
            try:
                maibot_dashboard.apply_dashboard_compat(target, expected_pin=PINNED_REVISION)
                maibot_dashboard.build_dashboard(target)
            except maibot_dashboard.DashboardCompatError as exc:
                raise MaiBotInstallError(str(exc)) from None
            if dependency_hash(target) != dependencies:
                raise MaiBotInstallError("配置初始化后关键依赖文件发生变化，拒绝完成安装")
            if not _is_complete_install(target):
                raise MaiBotInstallError("最终路径校验失败，安装保持 incomplete")
            marker = _read_install_marker(target)
            if marker is None or marker["state"] != "incomplete" or marker["dependency_hash"] != dependencies:
                raise MaiBotInstallError("安装标记在过程中发生变化，拒绝完成安装")
            _write_install_marker(target, state="complete", dependencies=dependencies)
        except MaiBotInstallError as exc:
            raise MaiBotInstallError(
                f"{exc}；固定版本源码已发布，安装状态保留为 incomplete，可重新执行 pallas maibot install 重试"
            ) from None
        except OSError:
            raise MaiBotInstallError(
                "安装文件系统 IO 失败；固定版本源码已发布，安装状态保留为 incomplete，"
                "可重新执行 pallas maibot install 重试"
            ) from None

    print(f"MaiBot 已安装固定版本 {PINNED_REVISION[:12]}：{target}")
    print("尚未接受协议或启动实例；模型配置由 MaiBot 原生管理。")
    print("查看协议：pallas maibot terms；显式确认：pallas maibot accept --eula --privacy")
    print(
        f"在 config/pallas.toml 的 [env] 中设置 {MANAGED_DIR_KEY} = "
        f"{json.dumps(str(target), ensure_ascii=False)}，并设置 MAIBOT_MANAGED_ENABLED = true。"
    )
    print("之后使用 Pallas 的 run/stop/restart 统一启停；此命令不会启动 MaiBot。")
    return target


def show_status() -> int:
    target = selected_maibot_dir()
    print(f"MaiBot 目录：{target}")
    print(f"安装：{installation_status(target)}")
    if not target.is_dir():
        print("源码：未安装")
        revision = ""
    else:
        try:
            revision = _read_revision(target)
        except MaiBotInstallError:
            revision = ""
        if revision == PINNED_REVISION:
            print(f"源码：固定版本 {revision}")
        elif revision:
            print(f"源码：未受支持版本 {revision}")
        else:
            print("源码：未检测到 Git 版本")

    python = _python_path(target)
    python_state = "可用" if python.is_file() else "缺失"
    print(f"Python：{python_state}，版本 {_python_version(python, target)}（{python}）")
    for filename in ("bot_config.toml", "model_config.toml"):
        state = "存在" if (target / "config" / filename).is_file() else "缺失"
        print(f"配置 {filename}：{state}")

    problems = protocol_problems(target)
    print(f"协议：{'已确认' if not problems else '需要确认或重新确认'}")
    for problem in problems:
        print(f"  · {problem}")
    try:
        managed = maibot_aux.managed_runtime_state()
    except Exception:
        managed = "invalid"
    managed_label = {
        "off": "未开启",
        "invalid": "配置无效",
        "running": "运行中",
        "not_running": "已开启但未运行",
    }.get(managed, "状态未知")
    print(f"托管：{managed_label}")
    print("统一启停：使用 Pallas 的 run/stop/restart；本命令不会另行启动进程。")
    return 0


def show_terms() -> int:
    target = selected_maibot_dir()
    _assert_no_symlink_components(target)
    for title, name in (("MaiBot EULA", "EULA.md"), ("MaiBot 隐私条款", "PRIVACY.md")):
        path = target / name
        if path.is_symlink() or not path.is_file():
            raise MaiBotInstallError(f"实际实例缺少可安全读取的条款文件：{name}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise MaiBotInstallError(f"无法读取条款文件：{name}") from None
        print(f"\n===== {title} ({path}) =====\n{text}")
    print("\n阅读后需分别显式执行：pallas maibot accept --eula --privacy")
    return 0


def accept_terms(*, eula: bool, privacy: bool) -> int:
    if not eula or not privacy:
        raise MaiBotInstallError("必须显式同时提供 --eula 与 --privacy")
    target = selected_maibot_dir()
    _assert_no_symlink_components(target)
    if not target.is_dir():
        raise MaiBotInstallError("未找到 MaiBot 实例；请先安装固定版本")
    if shutil.which("git") is None:
        raise MaiBotInstallError("未找到 git，无法核实当前条款所属的固定版本")
    with _target_lock(target):
        try:
            if _read_revision(target) != PINNED_REVISION:
                raise MaiBotInstallError("当前实例不是固定支持版本，拒绝确认协议")
        except MaiBotInstallError:
            raise
        hashes: list[tuple[str, str]] = []
        for document, confirmation in (("EULA.md", "eula.confirmed"), ("PRIVACY.md", "privacy.confirmed")):
            path = target / document
            if path.is_symlink() or not path.is_file():
                raise MaiBotInstallError(f"缺少可安全读取的条款文件：{document}")
            try:
                content = path.read_text(encoding="utf-8").encode("utf-8")
            except (OSError, UnicodeDecodeError):
                raise MaiBotInstallError(f"无法读取条款文件：{document}") from None
            hashes.append((confirmation, hashlib.md5(content).hexdigest()))
        for name, _digest in hashes:
            if (target / name).is_symlink():
                raise MaiBotInstallError(f"确认文件是符号链接，拒绝写入：{name}")
        for name, digest in hashes:
            atomic_write_text(target / name, digest)
    print(f"已记录当前固定版本条款确认：{target}")
    print("确认仅对应这两份条款的当前内容；条款改变后必须重新显式确认。")
    return 0
