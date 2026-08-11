"""Docker 部署包下载后的安全校验、解包与程序文件应用。"""

from __future__ import annotations

import asyncio
import shutil
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from packages.pb_webui.manager import resolve_github_release_asset_urls
from pallas.core.shared.utils.stream_download import sync_stream_download_to_file


class ReleaseBundleError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseBundle:
    tag: str
    root: Path


PROTECTED_TOP_LEVEL = {".git", "data", "local"}
MERGED_DIRECTORIES = {"config", "resource"}
PROTECTED_MERGED_PATHS = {
    PurePosixPath("config/pallas.toml"),
    PurePosixPath("config/pallas.webui.export.toml"),
    PurePosixPath("config/compose.env"),
    PurePosixPath("resource/voices"),
}


def validate_member(member: tarfile.TarInfo) -> PurePosixPath:
    raw = member.name or ""
    if not raw or raw.startswith(("/", "\\")) or "\\" in raw:
        raise ReleaseBundleError(f"发布包包含禁止的绝对路径：{raw}")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ReleaseBundleError(f"发布包路径越界：{raw}")
    if member.issym() or member.islnk():
        raise ReleaseBundleError(f"发布包包含不允许的链接：{raw}")
    if not (member.isfile() or member.isdir()):
        raise ReleaseBundleError(f"发布包包含不允许的文件类型：{raw}")
    return path


def safe_extract_release_bundle(archive_path: Path, stage_dir: Path, *, expected_tag: str) -> ReleaseBundle:
    expected = (expected_tag or "").strip()
    expected_root = f"pallas-bot-{expected}"
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            paths = [validate_member(member) for member in members]
            roots = {path.parts[0] for path in paths if path.parts}
            if roots != {expected_root}:
                raise ReleaseBundleError(
                    f"发布包版本或根目录不匹配：期望 {expected_root}，实际 {', '.join(sorted(roots)) or '(空)'}"
                )
            stage_dir.mkdir(parents=True, exist_ok=True)
            archive.extractall(stage_dir, members=members, filter="data")
    except ReleaseBundleError:
        raise
    except (OSError, tarfile.TarError) as err:
        raise ReleaseBundleError(f"无法读取发布包：{err}") from err

    root = stage_dir / expected_root
    required = (root / "pyproject.toml", root / "uv.lock", root / "pallas", root / "packages")
    if not all(path.exists() for path in required):
        raise ReleaseBundleError("发布包结构不完整：缺少 pyproject.toml、uv.lock、pallas 或 packages")
    return ReleaseBundle(tag=expected, root=root)


def is_protected_merged_path(relative: PurePosixPath) -> bool:
    return any(relative == protected or protected in relative.parents for protected in PROTECTED_MERGED_PATHS)


def merge_directory(source: Path, target: Path, *, top_level: str) -> int:
    applied = 0
    for source_path in source.rglob("*"):
        relative = PurePosixPath(top_level, *source_path.relative_to(source).parts)
        if is_protected_merged_path(relative):
            continue
        target_path = target.joinpath(*source_path.relative_to(source).parts)
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        applied += 1
    return applied


def replace_directory(source: Path, target: Path) -> int:
    backup = target.with_name(f".{target.name}.pallas-update-backup-{uuid.uuid4().hex}")
    if target.exists():
        target.rename(backup)
    try:
        shutil.copytree(source, target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        if backup.exists():
            backup.rename(target)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    return sum(1 for path in source.rglob("*") if path.is_file())


def replace_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.pallas-update-{uuid.uuid4().hex}")
    shutil.copy2(source, staged)
    staged.replace(target)


def apply_release_bundle(bundle: ReleaseBundle, target_root: Path) -> dict[str, Any]:
    target_root.mkdir(parents=True, exist_ok=True)
    applied = 0
    for source in bundle.root.iterdir():
        if source.name in PROTECTED_TOP_LEVEL:
            continue
        target = target_root / source.name
        if source.is_dir():
            if source.name in MERGED_DIRECTORIES:
                applied += merge_directory(source, target, top_level=source.name)
            else:
                applied += replace_directory(source, target)
            continue
        replace_file(source, target)
        applied += 1
    return {"tag": bundle.tag, "applied_file_count": applied}


async def install_docker_release_bundle(
    *,
    target_root: Path,
    repo: str,
    tag: str,
    github_token: str = "",
    on_progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    release_tag = (tag or "").strip()
    if not release_tag:
        raise ReleaseBundleError("缺少 Release 版本")

    def report(percent: int, message: str) -> None:
        if on_progress is not None:
            on_progress(percent, message)

    asset = f"pallas-bot-{release_tag}.tar.gz"
    report(5, "解析 Release 下载地址…")
    urls = await resolve_github_release_asset_urls(repo, asset, release_tag, token=github_token)
    if not urls:
        raise ReleaseBundleError(f"Release {release_tag} 缺少部署包 {asset}")

    with tempfile.TemporaryDirectory(prefix="pallas-bot-release-") as tmp:
        temp_root = Path(tmp)
        archive_path = temp_root / asset
        errors: list[str] = []
        report(15, "下载 Release 部署包…")
        for url in urls:
            try:
                await asyncio.to_thread(sync_stream_download_to_file, url, archive_path)
                errors.clear()
                break
            except Exception as err:  # noqa: BLE001
                errors.append(f"{url}: {err}")
        if errors:
            raise ReleaseBundleError("Release 部署包下载失败：" + " | ".join(errors))

        report(60, "校验并解压 Release 部署包…")
        bundle = await asyncio.to_thread(
            safe_extract_release_bundle,
            archive_path,
            temp_root / "stage",
            expected_tag=release_tag,
        )
        report(75, "应用 Release 程序文件…")
        result = await asyncio.to_thread(apply_release_bundle, bundle, target_root)
    return result
