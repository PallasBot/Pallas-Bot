"""Fixed, verifiable subpath build for the pinned MaiBot dashboard."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from pallas.console.cli import maibot_aux

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

PIN = "062d45cf8bd4272ac57d7ec03fcf405e5a458211"
PATCH_SHA256 = "89f26951c90b6a125a350a11917fcf6ba84b3ec92c1b8472f5451bea84f66e7b"
MANIFEST_SHA256 = "01f0ffd4af38f5e95da1d197b0a51693ccd97444474c682140fbe2f8be72e7d7"
PACKAGE_JSON_SHA256 = "b8c26a60286294d8cd504052c14e66e3bfe3e817f9d98df13a8a26d6eff52922"
PACKAGE_LOCK_SHA256 = "4b7b442e92d785c04097305f5363490021eeba6d11d664345c772584160e893e"
BASE_PATH = "/pallas/maibot/"
INSTALL_MARKER_NAME = ".pallas-maibot-install.json"
BUILD_MARKER_NAME = ".pallas-dashboard-build.json"
BUILD_SCHEMA = 1
GIT_TIMEOUT_S = 60.0
NODE_TIMEOUT_S = 15.0
NPM_CI_TIMEOUT_S = 1800.0
NPM_BUILD_TIMEOUT_S = 1200.0

_PACKAGE = "pallas.product.agent_bridge"
_DASHBOARD_ASSETS = files(_PACKAGE).joinpath("dashboard_compat")
_MARKER_FIELDS = {"schema", "base", "pin", "patch_sha256", "manifest_sha256", "source_hashes", "files"}


class DashboardCompatError(RuntimeError):
    """The pinned dashboard source, build, or path is unsafe or incomplete."""


def _resource(name: str) -> bytes:
    if name not in {"front-end.patch", "manifest.json"}:
        raise DashboardCompatError("未知 MaiBot dashboard 兼容资源")
    try:
        content = _DASHBOARD_ASSETS.joinpath(name).read_bytes()
    except (OSError, ModuleNotFoundError, TypeError):
        raise DashboardCompatError("MaiBot dashboard 兼容资源缺失") from None
    expected = PATCH_SHA256 if name == "front-end.patch" else MANIFEST_SHA256
    if hashlib.sha256(content).hexdigest() != expected:
        raise DashboardCompatError("MaiBot dashboard 兼容资源哈希不匹配")
    return content


def _manifest() -> dict:
    try:
        manifest = json.loads(_resource("manifest.json"))
    except (UnicodeDecodeError, ValueError):
        raise DashboardCompatError("MaiBot dashboard 清单无效") from None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    build = manifest.get("build") if isinstance(manifest, dict) else None
    files_list = manifest.get("files") if isinstance(manifest, dict) else None
    if (
        not isinstance(files_list, list)
        or len(files_list) != 30
        or not isinstance(source, dict)
        or source.get("commit") != PIN
        or not isinstance(build, dict)
        or build.get("maibot_subpath") != BASE_PATH
    ):
        raise DashboardCompatError("MaiBot dashboard 固定清单无效")
    seen: set[str] = set()
    for item in files_list:
        if not isinstance(item, dict) or set(item) != {"path", "sha256_before", "sha256_after"}:
            raise DashboardCompatError("MaiBot dashboard 文件清单无效")
        name, before, after = item["path"], item["sha256_before"], item["sha256_after"]
        relative = PurePosixPath(name) if isinstance(name, str) else PurePosixPath("/")
        if (
            not isinstance(name, str)
            or "\x00" in name
            or "\\" in name
            or relative.is_absolute()
            or relative.parts[:1] != ("dashboard",)
            or ".." in relative.parts
            or name in seen
            or (before is not None and not _is_sha256(before))
            or not _is_sha256(after)
        ):
            raise DashboardCompatError("MaiBot dashboard 清单路径或哈希无效")
        seen.add(name)
    return manifest


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _safe_root(root: Path) -> Path:
    root = Path(os.path.abspath(root.expanduser()))  # noqa: PTH100 — inspect symlinks before resolving
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if current.is_symlink():
            raise DashboardCompatError("MaiBot dashboard 路径包含符号链接")
    if not root.is_dir() or root.resolve() != root:
        raise DashboardCompatError("MaiBot dashboard 根目录无效")
    return root


def _safe_path(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise DashboardCompatError("MaiBot dashboard 路径越界") from None
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise DashboardCompatError("MaiBot dashboard 文件包含符号链接")


def _source_snapshot(root: Path, manifest: dict) -> tuple[str, list[tuple[dict, Path, bytes | None, int]]]:
    dashboard = root / "dashboard"
    _safe_path(root, dashboard)
    if not dashboard.is_dir():
        if dashboard.exists():
            raise DashboardCompatError("MaiBot dashboard 不是安全目录")
        return "missing", []
    entries = []
    states: set[str] = set()
    for item in manifest["files"]:
        path = root / item["path"]
        _safe_path(root, path)
        if not path.exists():
            if item["sha256_before"] is None:
                entries.append((item, path, None, 0o644))
                states.add("original")
                continue
            raise DashboardCompatError("MaiBot dashboard 补丁源文件缺失")
        if not path.is_file():
            raise DashboardCompatError("MaiBot dashboard 补丁目标不是普通文件")
        try:
            content = path.read_bytes()
        except OSError:
            raise DashboardCompatError("无法读取 MaiBot dashboard 补丁源文件") from None
        digest = hashlib.sha256(content).hexdigest()
        if digest == item["sha256_before"]:
            states.add("original")
        elif digest == item["sha256_after"]:
            states.add("patched")
        else:
            raise DashboardCompatError("MaiBot dashboard 源文件哈希未知")
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            raise DashboardCompatError("无法读取 MaiBot dashboard 补丁源文件权限") from None
        entries.append((item, path, content, mode))
    if len(states) != 1:
        raise DashboardCompatError("MaiBot dashboard 补丁处于混合状态")
    return states.pop(), entries


def _expected_source_hashes(manifest: dict) -> dict[str, str]:
    hashes = {item["path"]: item["sha256_after"] for item in manifest["files"]}
    hashes["dashboard/package.json"] = PACKAGE_JSON_SHA256
    hashes["dashboard/package-lock.json"] = PACKAGE_LOCK_SHA256
    return dict(sorted(hashes.items()))


def _artifact_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\x00" not in name
        and "\\" not in name
        and not path.is_absolute()
        and ".." not in path.parts
        and (
            name == "index.html"
            or name.startswith(("assets/", "fonts/"))
            or name in {"maimai.ico", "maibot_statistics.html"}
        )
    )


def _dist_files(dist: Path) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for path in dist.rglob("*"):
        if path.is_symlink():
            raise DashboardCompatError("MaiBot dashboard 构建产物包含符号链接")
        if path.is_dir():
            continue
        if not path.is_file():
            raise DashboardCompatError("MaiBot dashboard 构建产物不是普通文件")
        name = path.relative_to(dist).as_posix()
        if name != BUILD_MARKER_NAME and not _artifact_path(name):
            raise DashboardCompatError("MaiBot dashboard 构建产物包含未知文件")
        output[name] = path
    return output


def _inspect_build_dir(root: Path, dist: Path, source_state: str, manifest: dict) -> bool:
    _safe_path(root, dist)
    if not dist.exists():
        return False
    if not dist.is_dir():
        raise DashboardCompatError("MaiBot dashboard dist 不是安全目录")
    files_by_name = _dist_files(dist)
    marker_path = dist / BUILD_MARKER_NAME
    if not files_by_name:
        return False
    if marker_path not in files_by_name.values():
        raise DashboardCompatError("MaiBot dashboard dist 未受 Pallas 管理，拒绝覆盖")
    if source_state != "patched":
        raise DashboardCompatError("MaiBot dashboard 构建标记与源代码状态不符")
    _check_package_inputs(root / "dashboard")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise DashboardCompatError("MaiBot dashboard 构建标记无效") from None
    expected_sources = _expected_source_hashes(manifest)
    built = marker.get("files") if isinstance(marker, dict) else None
    if (
        not isinstance(marker, dict)
        or set(marker) != _MARKER_FIELDS
        or type(marker.get("schema")) is not int
        or marker.get("schema") != BUILD_SCHEMA
        or marker.get("base") != BASE_PATH
        or marker.get("pin") != PIN
        or marker.get("patch_sha256") != PATCH_SHA256
        or marker.get("manifest_sha256") != MANIFEST_SHA256
        or marker.get("source_hashes") != expected_sources
        or not isinstance(built, dict)
        or not built
        or any(not _artifact_path(name) or not _is_sha256(digest) for name, digest in built.items())
        or set(built) != set(files_by_name) - {BUILD_MARKER_NAME}
        or "index.html" not in built
        or not any(name.startswith("assets/") and name.endswith(".js") for name in built)
        or not any(name.startswith("assets/") and name.endswith(".css") for name in built)
    ):
        raise DashboardCompatError("MaiBot dashboard 构建标记与固定产物不符")
    for name, path in files_by_name.items():
        if name != BUILD_MARKER_NAME and hashlib.sha256(path.read_bytes()).hexdigest() != built[name]:
            raise DashboardCompatError("MaiBot dashboard 构建产物哈希不匹配")
    proxy = manifest.get("proxy_contract", {})
    required = {"index.html", "maimai.ico"} | {f"fonts/{name}" for name in proxy.get("font_files", [])}
    if not required.issubset(built):
        raise DashboardCompatError("MaiBot dashboard 构建产物不完整")
    try:
        index = (dist / "index.html").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise DashboardCompatError("MaiBot dashboard index.html 无效") from None
    if BASE_PATH not in index:
        raise DashboardCompatError("MaiBot dashboard 未按固定子路径构建")
    return True


def _inspect_build(root: Path, source_state: str, manifest: dict) -> bool:
    return _inspect_build_dir(root, root / "dashboard" / "dist", source_state, manifest)


def dashboard_state(root: Path) -> str:
    """Return missing, original, patched, or built; unknown states fail closed."""
    try:
        root = _safe_root(root)
        _resource("front-end.patch")
        manifest = _manifest()
        source_state, _ = _source_snapshot(root, manifest)
        if source_state == "missing":
            return source_state
        _check_package_inputs(root / "dashboard")
        return "built" if _inspect_build(root, source_state, manifest) else source_state
    except DashboardCompatError:
        raise
    except OSError:
        raise DashboardCompatError("无法安全核实 MaiBot dashboard 状态") from None


def validate_dashboard_build(root: Path) -> bool:
    try:
        return dashboard_state(root) == "built"
    except DashboardCompatError:
        return False


def _stage_file(path: Path, content: bytes, mode: int, *, prefix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def apply_dashboard_compat(root: Path, expected_pin: str = PIN) -> str:
    """Apply the bundled git patch after validating every fixed source hash."""
    if expected_pin != PIN:
        raise DashboardCompatError("MaiBot dashboard 固定版本不受支持")
    patch = _resource("front-end.patch")
    root = _safe_root(root)
    manifest = _manifest()
    state, sources = _source_snapshot(root, manifest)
    if state in {"patched", "missing"}:
        if state == "missing":
            raise DashboardCompatError("MaiBot dashboard 源码缺失")
        _inspect_build(root, state, manifest)
        return "patched"
    _inspect_build(root, state, manifest)
    workspace = Path(tempfile.mkdtemp(prefix=".pallas-dashboard-compat-stage-", dir=root))
    staged: list[tuple[Path, Path, Path | None, bool]] = []
    backups: list[Path] = []
    preserved: set[Path] = set()
    created_dirs: list[Path] = []
    committed = False
    try:
        patch_path = workspace / ".pallas-dashboard.patch"
        patch_path.write_bytes(patch)
        for item, _path, content, mode in sources:
            if content is None:
                continue
            stage_path = workspace / item["path"]
            stage_path.parent.mkdir(parents=True, exist_ok=True)
            stage_path.write_bytes(content)
            stage_path.chmod(mode)
        try:
            result = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=workspace,
                check=False,
                capture_output=True,
                timeout=GIT_TIMEOUT_S,
            )
        except FileNotFoundError:
            raise DashboardCompatError("未找到 git，无法应用 MaiBot dashboard 固定补丁") from None
        except subprocess.TimeoutExpired:
            raise DashboardCompatError("MaiBot dashboard 固定补丁应用超时") from None
        except OSError:
            raise DashboardCompatError("无法执行 MaiBot dashboard 固定补丁") from None
        if result.returncode:
            raise DashboardCompatError("MaiBot dashboard 固定补丁无法应用到原始源码")
        for item, path, original, mode in sources:
            patched_path = workspace / item["path"]
            content = patched_path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256_after"]:
                raise DashboardCompatError("MaiBot dashboard 固定补丁输出哈希不匹配")
            _safe_path(root, path.parent)
            missing_dirs = []
            parent = path.parent
            while parent != root and not parent.exists():
                missing_dirs.append(parent)
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(missing_dirs)
            original_mode = mode if original is not None else 0o644
            backup = (
                _stage_file(path, original, mode, prefix=".pallas-dashboard-compat-backup-")
                if original is not None
                else None
            )
            if backup is not None:
                backups.append(backup)
            replacement = _stage_file(path, content, original_mode, prefix=".pallas-dashboard-compat-stage-")
            staged.append((path, replacement, backup, original is not None))
        for path, replacement, _backup, _existed in staged:
            replacement.replace(path)
        committed = True
    except BaseException as exc:
        rollback_failures: list[tuple[Path, Path | None]] = []
        for path, _replacement, backup, _existed in reversed(staged):
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    backup.replace(path)
            except BaseException:
                if backup is not None:
                    preserved.add(backup)
                rollback_failures.append((path, backup))
        if rollback_failures:
            backups_to_report = [backup for _, backup in rollback_failures if backup is not None]
            if backups_to_report:
                locations = "、".join(f"[{path}]" for path in backups_to_report)
                raise DashboardCompatError(f"dashboard 补丁应用失败，回滚不完整；备份保留于 {locations}") from exc
            paths = "、".join(f"[{path}]" for path, _ in rollback_failures)
            raise DashboardCompatError(f"dashboard 补丁应用失败，回滚不完整；请检查路径 {paths}") from exc
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, DashboardCompatError):
            raise
        raise DashboardCompatError("MaiBot dashboard 应用补丁失败，原文件已恢复") from None
    finally:
        for _path, replacement, _backup, _existed in staged:
            try:
                replacement.unlink(missing_ok=True)
            except OSError:
                pass
        for backup in backups:
            if backup not in preserved:
                try:
                    backup.unlink(missing_ok=True)
                except OSError:
                    pass
        shutil.rmtree(workspace, ignore_errors=True)
        if not committed:
            for directory in sorted(set(created_dirs), key=lambda path: len(path.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
    return "patched"


def _run_process(command: list[str], *, cwd: Path, env: Mapping[str, str], timeout: float, label: str) -> str:
    try:
        result = subprocess.run(
            command,
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
        raise DashboardCompatError(f"未找到 {label} 所需命令") from None
    except subprocess.TimeoutExpired:
        raise DashboardCompatError(f"MaiBot dashboard {label} 超时") from None
    except OSError:
        raise DashboardCompatError(f"无法执行 MaiBot dashboard {label}") from None
    if result.returncode:
        raise DashboardCompatError(f"MaiBot dashboard {label} 失败（退出码 {result.returncode}）")
    return (result.stdout or "").strip()


def build_tools_error() -> str | None:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node:
        return "缺少 Node.js（需要 Node.js 22.12 或更高版本）"
    if not npm:
        return "缺少 npm"
    try:
        env = maibot_aux.build_managed_env(Path.cwd())
        version = _run_process(
            [node, "--version"], cwd=Path.cwd(), env=env, timeout=NODE_TIMEOUT_S, label="Node.js 检查"
        )
    except DashboardCompatError as exc:
        return str(exc)
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\+.*)?", version)
    if not match or (int(match[1]), int(match[2]), int(match[3])) < (22, 12, 0):
        return "Node.js 版本过低（需要 Node.js 22.12 或更高版本）"
    return None


def _build_environment(root: Path) -> dict[str, str]:
    try:
        env = maibot_aux.build_managed_env(root)
    except Exception:
        raise DashboardCompatError("无法创建隔离的 MaiBot dashboard 构建环境") from None
    env.update({
        "MAIBOT_DASHBOARD_BASE": BASE_PATH,
        "ELECTRON_SKIP_BINARY_DOWNLOAD": "1",
    })
    return env


def _git_output(command: list[str], *, root: Path, env: Mapping[str, str]) -> str:
    return _run_process(command, cwd=root, env=env, timeout=GIT_TIMEOUT_S, label="固定源码检查")


def _safe_git_paths(output: str) -> set[str]:
    paths = {item for item in output.split("\x00") if item}
    if any(
        "\x00" in item or "\\" in item or not item.startswith("dashboard/") or ".." in PurePosixPath(item).parts
        for item in paths
    ):
        raise DashboardCompatError("MaiBot dashboard Git 文件清单无效")
    return paths


def _check_pinned_dashboard(root: Path, manifest: dict, env: Mapping[str, str]) -> list[str]:
    _safe_path(root, root / ".git")
    if not (root / ".git").is_dir():
        raise DashboardCompatError("MaiBot dashboard 缺少固定 Git 源码目录")
    revision = _git_output(["git", "rev-parse", "HEAD"], root=root, env=env).lower()
    if revision != PIN:
        raise DashboardCompatError("MaiBot dashboard Git 版本与固定 pin 不符")
    tracked = _safe_git_paths(_git_output(["git", "ls-files", "-z", "--", "dashboard"], root=root, env=env))
    changed = _safe_git_paths(
        _git_output(["git", "diff", "--name-only", "-z", "HEAD", "--", "dashboard"], root=root, env=env)
    )
    untracked = _safe_git_paths(
        _git_output(["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "dashboard"], root=root, env=env)
    )
    expected_changed = {item["path"] for item in manifest["files"] if item["sha256_before"] is not None}
    expected_added = {item["path"] for item in manifest["files"] if item["sha256_before"] is None}
    if changed != expected_changed or untracked != expected_added:
        raise DashboardCompatError("MaiBot dashboard 包含固定补丁以外的源码变更")
    if not tracked:
        raise DashboardCompatError("MaiBot dashboard Git 源码清单为空")
    return sorted(tracked | untracked)


def _copy_build_sources(root: Path, destination: Path, paths: Iterable[str]) -> None:
    for name in paths:
        source = root / name
        _safe_path(root, source)
        if not source.is_file():
            raise DashboardCompatError("MaiBot dashboard 构建源码缺失")
        target = destination / PurePosixPath(name).relative_to("dashboard")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(stat.S_IMODE(source.stat().st_mode))


def _check_package_inputs(dashboard: Path) -> None:
    for name, expected in (("package.json", PACKAGE_JSON_SHA256), ("package-lock.json", PACKAGE_LOCK_SHA256)):
        path = dashboard / name
        try:
            valid = (
                not path.is_symlink() and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected
            )
        except OSError:
            valid = False
        if not valid:
            raise DashboardCompatError(f"MaiBot dashboard {name} 与固定版本不符")


def _check_install_marker(root: Path) -> None:
    marker = root / INSTALL_MARKER_NAME
    _safe_path(root, marker)
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise DashboardCompatError("MaiBot CLI 安装标记无效，拒绝构建前端") from None
    if (
        not isinstance(data, dict)
        or set(data) != {"pin", "state", "dependency_hash"}
        or data.get("pin") != PIN
        or data.get("state") != "incomplete"
        or not _is_sha256(data.get("dependency_hash"))
    ):
        raise DashboardCompatError("仅可为未完成的固定版本 MaiBot 安装构建前端")


def _build_marker(manifest: dict, dist: Path) -> dict:
    artifacts = _dist_files(dist)
    artifacts.pop(BUILD_MARKER_NAME, None)
    required = {"index.html", "maimai.ico"} | {f"fonts/{name}" for name in manifest["proxy_contract"]["font_files"]}
    if (
        not required.issubset(artifacts)
        or not any(name.startswith("assets/") and name.endswith(".js") for name in artifacts)
        or not any(name.startswith("assets/") and name.endswith(".css") for name in artifacts)
    ):
        raise DashboardCompatError("MaiBot dashboard 构建产物不完整")
    try:
        index = (dist / "index.html").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise DashboardCompatError("MaiBot dashboard index.html 无效") from None
    if BASE_PATH not in index:
        raise DashboardCompatError("MaiBot dashboard 未按固定子路径构建")
    return {
        "schema": BUILD_SCHEMA,
        "base": BASE_PATH,
        "pin": PIN,
        "patch_sha256": PATCH_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "source_hashes": _expected_source_hashes(manifest),
        "files": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(artifacts.items())},
    }


def _publish_build(root: Path, staged_dist: Path, dashboard: Path) -> None:
    target = dashboard / "dist"
    _safe_path(root, target)
    backup: Path | None = None
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise DashboardCompatError("MaiBot dashboard dist 已有未知内容，拒绝覆盖")
        backup = Path(tempfile.mkdtemp(prefix=".pallas-dashboard-dist-backup-", dir=root))
        backup.rmdir()
        target.replace(backup)
    try:
        staged_dist.replace(target)
    except OSError:
        if backup is not None:
            try:
                backup.replace(target)
            except OSError:
                raise DashboardCompatError(
                    f"MaiBot dashboard 构建发布失败，回滚不完整；备份保留于 [{backup}]"
                ) from None
        raise DashboardCompatError("MaiBot dashboard 构建发布失败，原目录已恢复") from None
    if backup is not None:
        try:
            backup.rmdir()
        except OSError:
            raise DashboardCompatError(f"前端已发布，但空备份目录清理失败；备份保留于 [{backup}]") from None


def build_dashboard(root: Path) -> None:
    """Build and publish only the pinned, patched source under the installer lock."""
    root = _safe_root(root)
    _resource("front-end.patch")
    _check_install_marker(root)
    manifest = _manifest()
    state, _ = _source_snapshot(root, manifest)
    if state != "patched":
        raise DashboardCompatError("MaiBot dashboard 必须先应用固定补丁才能构建")
    if _inspect_build(root, state, manifest):
        return
    dashboard = root / "dashboard"
    _check_package_inputs(dashboard)
    tool_problem = build_tools_error()
    if tool_problem:
        raise DashboardCompatError(tool_problem)
    env = _build_environment(root)
    tracked_paths = _check_pinned_dashboard(root, manifest, env)
    stage_root = Path(tempfile.mkdtemp(prefix=".pallas-dashboard-build-", dir=root))
    try:
        staged_dashboard = stage_root / "dashboard"
        _copy_build_sources(root, staged_dashboard, tracked_paths)
        _check_package_inputs(staged_dashboard)
        _run_process(
            ["npm", "ci", "--no-audit", "--no-fund"],
            cwd=staged_dashboard,
            env=env,
            timeout=NPM_CI_TIMEOUT_S,
            label="npm ci",
        )
        _check_package_inputs(staged_dashboard)
        staged_dist = stage_root / "dist"
        _run_process(
            ["npm", "run", "build", "--", "--outDir", str(staged_dist)],
            cwd=staged_dashboard,
            env=env,
            timeout=NPM_BUILD_TIMEOUT_S,
            label="浏览器构建",
        )
        if not staged_dist.is_dir():
            raise DashboardCompatError("MaiBot dashboard 浏览器构建没有生成 dist")
        marker = _build_marker(manifest, staged_dist)
        marker_path = staged_dist / BUILD_MARKER_NAME
        marker_path.write_text(json.dumps(marker, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        marker_path.chmod(0o600)
        if not _inspect_build_dir(root, staged_dist, state, manifest):
            raise DashboardCompatError("MaiBot dashboard 构建产物校验失败")
        _publish_build(root, staged_dist, dashboard)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    if not validate_dashboard_build(root):
        raise DashboardCompatError("MaiBot dashboard 发布后校验失败")
