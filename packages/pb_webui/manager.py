"""控制台静态资源：默认目录 data/pb_webui/public-react（React），可选 zip 直链下载解压。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable  # noqa: TC003
from operator import itemgetter
from pathlib import Path
from typing import Any

import httpx
from nonebot import logger

from packages.pb_webui.data_dir import pb_webui_data_dir
from pallas.core.foundation.bot_version import (
    get_bot_current_version,
    pallas_bot_repo_root,
)
from pallas.core.foundation.paths import resource_dir
from pallas.core.shared.utils.format_exception import format_exception_for_log
from pallas.core.shared.utils.git_mirror import (
    MirrorSpec,
    git_instead_of_args,
    iter_mirrors_for_failover,
    request_with_mirrors,
    resolve_mirror_for_scope,
    rewrite_github_url,
)
from pallas.core.shared.utils.github_release import (
    fetch_github_releases,
    fetch_latest_release,
    fetch_latest_release_tag_via_github_web,
    github_auth_headers,
    github_release_api_url,
    github_release_asset_url,
    github_release_asset_url_candidates,
    github_request_ssl_env,
    release_tags_equivalent,
)
from pallas.core.shared.utils.stream_download import (
    StreamDownloadProgress,
    format_download_byte_size,
    sync_stream_download_to_file,
)

ProgressReporter = Callable[[int, str], None]


async def resolve_github_release_asset_urls(
    repo: str,
    preferred_asset: str,
    tag: str = "",
    *,
    token: str = "",
) -> list[str]:
    """先查 release 资产列表再选下载 URL；失败时回退到直链候选。"""
    preferred = (preferred_asset or "").strip()
    if not preferred:
        raise ValueError("发布资产名不能为空")
    candidates: list[str] = []
    release_apis = [github_release_api_url(repo, tag)]
    if (tag or "").strip():
        release_apis.append(github_release_api_url(repo, ""))
    with github_request_ssl_env():
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
        ) as client:
            auth_headers = github_auth_headers(token)
            for api in release_apis:
                try:
                    resp = await client.get(api, headers=auth_headers)
                except Exception as e:
                    # API 失败仍会追加 releases/download 直链候选，默认不打 WARNING 以免刷屏
                    logger.debug(
                        "[WebUI] GitHub Release API 请求异常（将尝试直链）api={} err={}",
                        api,
                        format_exception_for_log(e),
                    )
                    continue
                if resp.status_code != 200:
                    logger.debug(
                        "[WebUI] GitHub Release API 非 200（将尝试直链）status={} api={}",
                        resp.status_code,
                        api,
                    )
                    continue
                data = resp.json()
                assets = data.get("assets")
                if not isinstance(assets, list):
                    continue
                urls: dict[str, str] = {}
                for item in assets:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    url = str(item.get("browser_download_url", "")).strip()
                    if not name or not url:
                        continue
                    urls[name] = url
                if preferred in urls:
                    candidates.append(urls[preferred])
                elif urls:
                    for name, url in urls.items():
                        if name.lower().endswith(".zip"):
                            candidates.append(url)
                            break
    # 追加直链候选
    candidates.extend(github_release_asset_url_candidates(repo, preferred, tag))
    dedup: list[str] = []
    seen: set[str] = set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        dedup.append(u)
    return dedup


class WebuiReleaseCompatibilityError(RuntimeError):
    """WebUI Release 缺少兼容当前 Bot 所需的发布信息。"""


def parse_webui_release_manifest(payload: object) -> dict[str, int | str]:
    """校验 WebUI Release manifest，并返回兼容检查所需字段。"""
    if not isinstance(payload, dict):
        raise ValueError("WebUI release manifest 必须是 JSON 对象")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise ValueError("WebUI release manifest 的 schema_version 必须为 1")
    requires = payload.get("requires")
    bot = requires.get("bot") if isinstance(requires, dict) else None
    minimum = bot.get("min_commit") if isinstance(bot, dict) else None
    if not isinstance(minimum, str) or not re.fullmatch(r"[0-9a-f]{40}", minimum):
        raise ValueError("WebUI release manifest 缺少有效的 Bot min_commit")
    return {"schema_version": 1, "min_bot_commit": minimum}


async def _fetch_webui_release_list(repo: str, *, token: str = "") -> list[dict[str, Any]]:
    with github_request_ssl_env():
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
        ) as client:
            return await fetch_github_releases(
                repo,
                client=client,
                limit=None,
                token=token,
                mirror_scope="webui",
            )


async def _fetch_webui_release_manifest(url: str, *, token: str = "") -> object:
    manifest_url = (url or "").strip()
    if not manifest_url:
        raise ValueError("WebUI Release 缺少 release-manifest.json 资产")
    headers = {"User-Agent": "Pallas-Bot-PallasWebUI/1.0"}
    headers.update(github_auth_headers(token))
    with github_request_ssl_env():
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
        ) as client:

            async def getter(url: str) -> httpx.Response:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response

            response = await request_with_mirrors(
                manifest_url,
                list(iter_mirrors_for_failover("webui")),
                getter,
            )
            return response.json()


DEFAULT_WEBUI_DIST_ZIP_REPO = "PallasBot/Pallas-Bot-WebUI"
DEFAULT_WEBUI_DIST_ZIP_ASSET = "dist.zip"
BUNDLED_WEBUI_DIST_ZIP = resource_dir("webui", "dist.zip")


def normalize_webui_dist_zip_repo(value: object) -> str:
    repo = str(value or "").strip()
    if repo == "PallasBot/Pallas-Bot":
        return DEFAULT_WEBUI_DIST_ZIP_REPO
    return repo


def webui_frontend_stack() -> str:
    """返回 vue|react；供静态目录与 console meta 共用。默认 react。"""
    try:
        from .config import plugin_config

        raw = str(getattr(plugin_config, "pallas_webui_frontend", "react") or "react")
    except Exception:
        raw = "react"
    stack = raw.strip().lower()
    return "vue" if stack == "vue" else "react"


def webui_public_path() -> Path:
    """React → public-react；Vue → public（见 pallas_webui_frontend）。"""
    if webui_frontend_stack() == "vue":
        return pb_webui_data_dir() / "public"
    return pb_webui_data_dir() / "public-react"


def check_webui_exists(path: Path) -> bool:
    return (path / "index.html").is_file()


def _resolved_extract_root(archive_dir: Path) -> Path:
    for name in ("public-react", "public"):
        cand = archive_dir / name
        if cand.is_dir() and (cand / "index.html").is_file():
            return cand
    if (archive_dir / "index.html").is_file():
        return archive_dir
    subdirs = [d for d in archive_dir.iterdir() if d.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / "index.html").is_file():
        return subdirs[0]
    if len(subdirs) == 1:
        return subdirs[0]
    return archive_dir


def _safe_extract_zip(zf: zipfile.ZipFile, extract_root: Path) -> None:
    """防 Zip Slip：逐成员校验解析后路径必须落在 extract_root 内部。"""
    root = extract_root.resolve()
    for member in zf.infolist():
        raw_name = member.filename or ""
        if not raw_name:
            continue
        # 拒绝绝对路径与 Windows 驱动器/UNC 前缀
        if raw_name.startswith(("/", "\\")) or (len(raw_name) >= 2 and raw_name[1] == ":"):
            msg = f"禁止的 ZIP 路径（绝对路径）: {raw_name}"
            raise ValueError(msg)
        dest = (root / raw_name).resolve()
        if dest != root and not dest.is_relative_to(root):
            msg = f"禁止的 ZIP 路径（越界）: {raw_name}"
            raise ValueError(msg)
        if member.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _sync_extract_dist_zip_file(zip_path: Path, public_dir: Path) -> None:
    public_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tpath = Path(tmp)
        extract_root = tpath / "extracted"
        extract_root.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract_zip(zf, extract_root)
        source = _resolved_extract_root(extract_root)
        if public_dir.exists():
            shutil.rmtree(public_dir)
        public_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, public_dir, dirs_exist_ok=True)


def _read_webui_release_manifest_from_archive(archive_path: Path) -> dict[str, int | str]:
    with zipfile.ZipFile(archive_path) as zf:
        manifests = [
            member
            for member in zf.infolist()
            if not member.is_dir()
            and member.filename.replace("\\", "/").rstrip("/").split("/")[-1] == "release-manifest.json"
        ]
        if not manifests:
            raise ValueError("WebUI dist 缺少 release-manifest.json")
        if len(manifests) > 1:
            raise ValueError("WebUI dist 包含多个 release-manifest.json")
        try:
            payload = json.loads(zf.read(manifests[0]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("WebUI dist 的 release-manifest.json 无效") from e
    return parse_webui_release_manifest(payload)


async def validate_webui_dist_archive(
    archive_path: Path,
    *,
    token: str = "",
    current_commit: str | None = None,
) -> dict[str, int | str]:
    """在安装前校验 WebUI 压缩包声明的 Bot 兼容基线。"""
    manifest = await asyncio.to_thread(_read_webui_release_manifest_from_archive, archive_path)
    bot_commit = (current_commit if current_commit is not None else get_bot_current_commit()).strip()
    if re.fullmatch(r"[0-9a-f]{40}", bot_commit) is None:
        raise WebuiReleaseCompatibilityError("当前 Bot 没有可用于兼容性检查的完整 commit")
    minimum = str(manifest["min_bot_commit"])
    if not await is_bot_commit_compatible(minimum, bot_commit, token=token):
        raise WebuiReleaseCompatibilityError("WebUI dist 与当前 Bot 不兼容")
    return manifest


async def extract_bundled_webui_dist(
    public_dir: Path,
    archive_path: Path = BUNDLED_WEBUI_DIST_ZIP,
    *,
    require_compatible_manifest: bool = False,
    token: str = "",
    current_commit: str | None = None,
) -> bool:
    if not await asyncio.to_thread(archive_path.is_file):
        return False
    try:
        if require_compatible_manifest:
            await validate_webui_dist_archive(
                archive_path,
                token=token,
                current_commit=current_commit,
            )
        await asyncio.to_thread(_sync_extract_dist_zip_file, archive_path, public_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WebUI] 内置 WebUI dist 解压失败：{}", format_exception_for_log(e))
        return False
    logger.info("[WebUI] 已从内置 dist 初始化静态资源")
    return True


def _sync_write_dist_from_zip_bytes(public_dir: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
        tf.write(content)
        zip_path = Path(tf.name)
    try:
        _sync_extract_dist_zip_file(zip_path, public_dir)
    finally:
        zip_path.unlink(missing_ok=True)


def _unlink_ignore_missing(path: Path) -> None:
    path.unlink(missing_ok=True)


def _webui_download_progress_log(ev: StreamDownloadProgress) -> None:
    if ev["event"] == "percent":
        logger.info(
            "[WebUI] WebUI dist 下载进度 {}%（{}/{}）",
            ev["milestone_percent"],
            format_download_byte_size(ev["received"]),
            format_download_byte_size(ev["total"]),
        )
    elif ev["event"] == "unknown_step":
        logger.info(
            "[WebUI] WebUI dist 已下载 {}（服务器未提供文件大小）",
            format_download_byte_size(ev["received"]),
        )
    elif ev["event"] == "complete":
        if ev["total"] is not None:
            logger.info(
                "[WebUI] WebUI dist 下载完成 {} / {}",
                format_download_byte_size(ev["received"]),
                format_download_byte_size(ev["total"]),
            )
        elif ev["received"] > 0:
            logger.info(
                "[WebUI] WebUI dist 下载完成 {}",
                format_download_byte_size(ev["received"]),
            )


def chain_webui_download_progress(
    *callbacks: Callable[[StreamDownloadProgress], None] | None,
) -> Callable[[StreamDownloadProgress], None]:
    active = [cb for cb in callbacks if cb is not None]

    def _fanout(ev: StreamDownloadProgress) -> None:
        for cb in active:
            cb(ev)

    return _fanout


def map_webui_download_progress(
    report: ProgressReporter | None,
    *,
    base: int = 8,
    span: int = 72,
) -> Callable[[StreamDownloadProgress], None] | None:
    """将下载事件映射到整体进度区间 ``[base, base+span]``。"""
    if report is None:
        return None
    unknown_pct = base + 8

    def _on(ev: StreamDownloadProgress) -> None:
        nonlocal unknown_pct
        if ev["event"] == "percent":
            pct = base + int(ev["milestone_percent"] * span / 100)
            report(
                pct,
                f"下载中 {ev['milestone_percent']}%（{format_download_byte_size(ev['received'])}"
                f" / {format_download_byte_size(ev['total'])}）",
            )
        elif ev["event"] == "unknown_step":
            unknown_pct = min(base + span - 4, unknown_pct + 4)
            report(unknown_pct, f"下载中 {format_download_byte_size(ev['received'])}（未知总大小）")
        elif ev["event"] == "complete":
            size = format_download_byte_size(ev["received"])
            report(base + span, f"下载完成 {size}")

    return _on


def build_git_argv_with_mirror(mirror: MirrorSpec, *args: str) -> list[str]:
    return [*git_instead_of_args(mirror), *args]


def iter_failover_download_urls(url: str):
    u = (url or "").strip()
    if not u:
        return
    for mirror in iter_mirrors_for_failover("webui"):
        yield rewrite_github_url(u, mirror)


def iter_failover_download_attempts(url: str):
    """Yield ``(mirror_id, rewritten_url)`` for WebUI dist failover."""
    u = (url or "").strip()
    if not u:
        return
    for mirror in iter_mirrors_for_failover("webui"):
        yield mirror.id, rewrite_github_url(u, mirror)


def _sync_download_webui_zip(
    url: str,
    dest: Path,
    *,
    follow_redirects: bool,
    on_progress: Callable[[StreamDownloadProgress], None] | None = None,
) -> None:
    last_exc: Exception | None = None
    progress = chain_webui_download_progress(_webui_download_progress_log, on_progress)
    attempts = list(iter_failover_download_attempts(url))
    for i, (mirror_id, attempt_url) in enumerate(attempts, start=1):
        preview = attempt_url if len(attempt_url) <= 200 else attempt_url[:197] + "..."
        logger.info(
            "[WebUI] WebUI dist 尝试下载 {}/{} mirror={} {}",
            i,
            len(attempts),
            mirror_id,
            preview,
        )
        try:
            sync_stream_download_to_file(
                attempt_url,
                dest,
                follow_redirects=follow_redirects,
                timeout=httpx.Timeout(300.0, connect=60.0),
                progress_percent_step=5,
                on_progress=progress,
            )
            logger.info("[WebUI] WebUI dist download completed through mirror [{}]", mirror_id)
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            logger.warning(
                "[WebUI] WebUI dist download through mirror [{}] failed: [{}]",
                mirror_id,
                format_exception_for_log(e),
            )
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("无可用镜像源")


async def download_and_extract_dist_zip(
    public_dir: Path,
    url: str,
    *,
    follow_redirects: bool = True,
    on_download_progress: Callable[[StreamDownloadProgress], None] | None = None,
    on_stage: ProgressReporter | None = None,
    require_compatible_manifest: bool = False,
    github_token: str = "",
    current_commit: str | None = None,
) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    preferred = resolve_mirror_for_scope("webui")
    preview = url if len(url) <= 200 else url[:197] + "..."
    logger.info(
        "[WebUI] 正在下载 WebUI dist（首选镜像 {}，将按 failover 改写）{}",
        preferred.id,
        preview,
    )
    if on_stage is not None:
        on_stage(8, "开始下载 WebUI dist…")

    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = Path(tmp_zip.name)
    tmp_zip.close()

    try:
        await asyncio.to_thread(
            _sync_download_webui_zip,
            url,
            zip_path,
            follow_redirects=follow_redirects,
            on_progress=on_download_progress,
        )
        if on_stage is not None:
            stage_message = "正在校验 WebUI 兼容性…" if require_compatible_manifest else "正在解压 WebUI dist…"
            on_stage(82 if require_compatible_manifest else 85, stage_message)
        if require_compatible_manifest:
            await validate_webui_dist_archive(
                zip_path,
                token=github_token,
                current_commit=current_commit,
            )
            if on_stage is not None:
                on_stage(85, "正在解压 WebUI dist…")
        await asyncio.to_thread(_sync_extract_dist_zip_file, zip_path, public_dir)
        logger.info("[WebUI] 已解压 dist 到 {}", public_dir)
        if on_stage is not None:
            on_stage(92, "解压完成")
    finally:
        await asyncio.to_thread(_unlink_ignore_missing, zip_path)

    return True


def webui_version_path() -> Path:
    return pb_webui_data_dir() / "version.json"


def get_webui_dist_version() -> str:
    import json

    path = webui_public_path() / "console-version.json"
    if not path.exists():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return str(raw.get("version") or raw.get("tag") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def get_installed_webui_version() -> dict:
    import json

    path = webui_version_path()
    result: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            result = raw if isinstance(raw, dict) else {}
        except Exception:  # noqa: BLE001
            pass
    # version.json 没有 tag 时，从 dist 的 console-version.json 补充
    if not result.get("tag"):
        dist_ver = get_webui_dist_version()
        if dist_ver:
            result = {**result, "tag": dist_ver}
    return result


def save_installed_webui_version(tag: str, asset_url: str = "") -> None:
    """下载成功后写入版本信息。"""
    import json
    import time

    path = webui_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "tag": (tag or "").strip(),
        "asset_url": (asset_url or "").strip(),
        "installed_at": time.time(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_BOT_ROOT = pallas_bot_repo_root()


def inspect_bot_deployment() -> dict[str, str | bool | int]:
    """控制台 Bot 更新页：识别 git 工作副本 / 发布 tag / 开发克隆 / 镜像部署。"""
    import subprocess

    root = _BOT_ROOT
    info: dict[str, str | bool | int] = {
        "git_available": False,
        "dirty": False,
        "dirty_file_count": 0,
        "current_branch": "",
        "deployment_mode": "docker",
    }
    try:
        inside = (
            subprocess.check_output(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=root,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip()
            == "true"
        )
    except Exception:  # noqa: BLE001
        inside = False
    if not inside:
        from pallas.core.foundation.bot_version import get_bot_image_version, get_runtime_overlay_version

        image_version = get_bot_image_version()
        overlay_version = get_runtime_overlay_version()
        runtime_version = overlay_version or image_version
        info["image_version"] = image_version
        info["runtime_version"] = runtime_version
        info["container_overlay_update"] = bool(overlay_version and overlay_version != image_version)
        return info

    info["git_available"] = True
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        info["current_branch"] = branch
    except Exception:  # noqa: BLE001
        pass

    try:
        porcelain = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines = [ln for ln in porcelain.splitlines() if ln.strip()]
        info["dirty_file_count"] = len(lines)
        info["dirty"] = bool(lines)
    except Exception:  # noqa: BLE001
        pass

    current_tag = str(get_bot_current_version().get("tag", "") or "").strip()
    if current_tag:
        info["deployment_mode"] = "release_tag_dirty" if info["dirty"] else "release_tag"
    else:
        info["deployment_mode"] = "dev_clone"
    return info


def bot_git_head_and_release_shas(latest_tag: str) -> tuple[str, str] | None:
    """解析 HEAD 与 latest_tag 对应 commit；无 git 或解析失败返回 None。"""
    tag = (latest_tag or "").strip()
    if not tag:
        return None
    root = _BOT_ROOT
    if not (root / ".git").exists():
        return None

    def _git_rev_parse(ref: str) -> str:
        import subprocess

        return subprocess.check_output(
            ["git", "rev-parse", ref],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8.0,
        ).strip()

    try:
        latest_sha = _git_rev_parse(f"{tag}^{{commit}}")
        head_sha = _git_rev_parse("HEAD")
    except Exception:  # noqa: BLE001
        return None
    return head_sha, latest_sha


def bot_git_rev_list_count(revision_range: str) -> int:
    import subprocess

    root = _BOT_ROOT
    try:
        out = subprocess.check_output(
            ["git", "rev-list", "--count", revision_range],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8.0,
        ).strip()
    except Exception:  # noqa: BLE001
        return 0
    return int(out) if out.isdigit() else 0


def normalize_bot_update_track(value: object) -> str:
    track = str(value or "").strip().lower()
    return "branch" if track == "branch" else "release"


def _git_rev_parse_text(*args: str, timeout_s: float = 8.0) -> str | None:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", *args],
            cwd=_BOT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def get_bot_current_commit() -> str:
    """返回当前 Bot 的完整 Git commit；构建元数据可作为 Git 兜底。"""
    commit = _git_rev_parse_text("HEAD")
    if commit:
        return commit
    return (os.environ.get("PALLAS_BOT_COMMIT") or "").strip()


def is_bot_commit_ancestor(ancestor: str, descendant: str) -> bool:
    """判断 ``ancestor`` 是否已经包含在当前 Bot 的 ``descendant`` 历史中。"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=_BOT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8.0,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return False
    return result.returncode == 0


def _git_repository_is_shallow() -> bool | None:
    result = _git_rev_parse_text("--is-shallow-repository")
    if result == "true":
        return True
    if result == "false":
        return False
    return None


async def _fetch_bot_commit_compare_status(
    ancestor: str,
    descendant: str,
    *,
    token: str = "",
) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", ancestor) is None or re.fullmatch(r"[0-9a-f]{40}", descendant) is None:
        return ""
    compare_url = f"https://api.github.com/repos/PallasBot/Pallas-Bot/compare/{ancestor}...{descendant}"
    headers = {"User-Agent": "Pallas-Bot-PallasWebUI/1.0"}
    headers.update(github_auth_headers(token))
    with github_request_ssl_env():
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
        ) as client:

            async def getter(url: str) -> httpx.Response:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response

            try:
                response = await request_with_mirrors(
                    compare_url,
                    list(iter_mirrors_for_failover("bot")),
                    getter,
                )
                data = response.json()
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "[WebUI] Bot commit compare 请求失败：{}",
                    format_exception_for_log(e),
                )
                return ""
    return str(data.get("status") or "").strip().lower() if isinstance(data, dict) else ""


async def is_bot_commit_compatible(
    ancestor: str,
    descendant: str,
    *,
    token: str = "",
) -> bool:
    """判断 Bot 是否包含基线 commit，必要时用 GitHub compare 补足浅仓信息。"""
    if await asyncio.to_thread(is_bot_commit_ancestor, ancestor, descendant):
        return True
    shallow = await asyncio.to_thread(_git_repository_is_shallow)
    if shallow is False:
        return False
    status = await _fetch_bot_commit_compare_status(ancestor, descendant, token=token)
    return status in {"ahead", "identical"}


def resolve_bot_upstream_ref(*, preferred_branch: str = "") -> str:
    """解析分支更新目标，返回 ``origin/<branch>``；无法解析时返回空串。

    仅允许官方主干 ``dev`` / ``main``，避免跟踪 feature 或本地克隆分支。
    """
    import subprocess

    # 与 bot_git_manage.BOT_GIT_TRACK_BRANCHES 保持一致（避免循环 import）
    allowed = ("dev", "main")
    root = _BOT_ROOT
    preferred = (preferred_branch or "").strip().removeprefix("origin/")
    if preferred:
        if preferred not in allowed:
            return ""
        ref = f"origin/{preferred}"
        if _git_rev_parse_text("-q", "--verify", ref) is not None:
            return ref
        return ""

    upstream = _git_rev_parse_text("--abbrev-ref", "@{u}")
    if upstream and upstream != "HEAD" and "/" in upstream:
        short = upstream.removeprefix("origin/")
        if short in allowed:
            return upstream if upstream.startswith("origin/") else f"origin/{short}"

    branch = _git_rev_parse_text("--abbrev-ref", "HEAD") or ""
    if branch in allowed:
        ref = f"origin/{branch}"
        if _git_rev_parse_text("-q", "--verify", ref) is not None:
            return ref

    try:
        sym = subprocess.check_output(
            ["git", "symbolic-ref", "-q", "refs/remotes/origin/HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8.0,
        ).strip()
    except Exception:  # noqa: BLE001
        sym = ""
    if sym.startswith("refs/remotes/origin/"):
        short = sym.rsplit("/", maxsplit=1)[-1]
        if short in allowed:
            return f"origin/{short}"

    for cand in allowed:
        ref = f"origin/{cand}"
        if _git_rev_parse_text("-q", "--verify", ref) is not None:
            return ref
    return ""


def bot_branch_update_probe(*, preferred_branch: str = "") -> dict[str, object]:
    """相对已 fetch 的远端分支是否落后（不发起网络）。"""
    upstream = resolve_bot_upstream_ref(preferred_branch=preferred_branch)
    if not upstream:
        return {
            "has_update": False,
            "upstream_ref": "",
            "latest_commit": "",
            "commits_behind": 0,
            "error": "无法解析跟踪分支（请先 git fetch，或配置 pallas_bot_update_branch）",
        }
    head = _git_rev_parse_text("HEAD") or ""
    remote = _git_rev_parse_text(upstream) or ""
    if not head or not remote:
        return {
            "has_update": False,
            "upstream_ref": upstream,
            "latest_commit": "",
            "commits_behind": 0,
            "error": f"无法解析 HEAD 或 {upstream}",
        }
    behind = bot_git_rev_list_count(f"{head}..{remote}")
    short = remote[:12] if len(remote) >= 12 else remote
    return {
        "has_update": behind > 0,
        "upstream_ref": upstream,
        "latest_commit": short,
        "commits_behind": behind,
        "error": None,
    }


async def fetch_bot_origin_refs(*, on_progress: ProgressReporter | None = None) -> None:
    """仅 ``git fetch origin --tags``（带镜像故障转移），供分支轨道检查使用。"""
    root = _BOT_ROOT
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def report(pct: int, message: str) -> None:
        if on_progress is not None:
            on_progress(pct, message)

    async def git(
        *args: str,
        cmd_timeout_s: float = 180.0,
        mirror: MirrorSpec | None = None,
    ) -> tuple[int, str, str]:
        prefix = git_instead_of_args(mirror) if mirror is not None else []
        proc = await asyncio.create_subprocess_exec(
            "git",
            *prefix,
            *args,
            cwd=str(root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=cmd_timeout_s)
        except asyncio.TimeoutError:  # noqa: UP041
            proc.kill()
            await proc.wait()
            raise BotGitUpdateError("git 操作超时，请检查网络或稍后在命令行重试", status_code=504) from None
        out = out_b.decode(errors="replace").strip() if out_b else ""
        err = err_b.decode(errors="replace").strip() if err_b else ""
        return int(proc.returncode or 0), out, err

    report(10, "检查 git 工作副本…")
    rc, out, _ = await git("rev-parse", "--is-inside-work-tree")
    if rc != 0 or out != "true":
        raise BotGitUpdateError(
            "当前运行目录不是 git 工作副本，无法 fetch。",
            status_code=400,
        )

    report(40, "git fetch origin…")
    last_err = ""
    for i, mirror in enumerate(iter_mirrors_for_failover("bot"), start=1):
        code, _out, err = await git("fetch", "origin", "--tags", cmd_timeout_s=300.0, mirror=mirror)
        if code == 0:
            report(100, "fetch 完成")
            return
        last_err = err or f"exit={code}"
        logger.warning(
            "[WebUI] Bot git fetch mirror={} 失败：{}",
            mirror.id,
            last_err[:300],
        )
        _ = i
    raise BotGitUpdateError(f"git fetch 失败：{last_err or '(无 stderr)'}", status_code=502)


def bot_has_release_update(
    *,
    latest_tag: str,
    current_tag: str = "",
    current_commit: str = "",
) -> bool:
    """是否落后于 GitHub 最新 release。

    当前 HEAD 相对 latest 有超前 commit（开发分支 / 分叉）时不提示「有更新」，
    避免在 4.x 开发线上误报可升级到旧的 3.x release。
    """
    from pallas.core.shared.utils.github_release import release_tags_equivalent

    tag = (latest_tag or "").strip()
    if not tag:
        return False
    if release_tags_equivalent(current_tag, tag):
        return False
    shas = bot_git_head_and_release_shas(tag)
    if shas is None:
        cur = (current_tag or "").strip()
        return bool(cur) and not release_tags_equivalent(cur, tag)
    head_sha, latest_sha = shas
    if head_sha == latest_sha:
        return False
    ahead = bot_git_rev_list_count(f"{latest_sha}..{head_sha}")
    if ahead > 0:
        return False
    return bot_git_rev_list_count(f"{head_sha}..{latest_sha}") > 0


def is_bot_release_style_tag(tag: str) -> bool:
    """是否为 Bot Release 风格标签（``v1.2.3``），用于区分本地 npm 版号。"""
    t = (tag or "").strip()
    if len(t) < 2 or t[0] not in {"v", "V"}:
        return False
    return t[1].isdigit()


def webui_has_release_update(*, latest_tag: str, current_tag: str) -> bool:
    """WebUI dist 是否落后于 GitHub 最新正式 release。

    本地 ``console-version.json`` 的 npm 版号（如 ``0.6.35``）不可比。
    """
    from pallas.core.shared.utils.github_release import release_tags_equivalent

    latest = (latest_tag or "").strip()
    current = (current_tag or "").strip()
    if not latest or not current:
        return False
    if not is_bot_release_style_tag(latest) or not is_bot_release_style_tag(current):
        return False
    return not release_tags_equivalent(current, latest)


def _webui_release_asset_url(release: dict[str, Any], asset_name: str) -> str:
    preferred = (asset_name or "").strip().lower()
    if not preferred:
        return ""
    assets = release.get("assets")
    if not isinstance(assets, list):
        return ""
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip().lower()
        if name != preferred:
            continue
        return str(asset.get("url") or asset.get("browser_download_url") or "").strip()
    return ""


def _webui_release_version_key(tag: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(
        r"[vV](\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\+[0-9A-Za-z.-]+)?",
        (tag or "").strip(),
    )
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


async def resolve_compatible_webui_release(
    repo: str,
    preferred_asset: str = DEFAULT_WEBUI_DIST_ZIP_ASSET,
    tag: str = "",
    *,
    token: str = "",
    current_commit: str | None = None,
) -> dict[str, Any]:
    """选择与当前 Bot commit 兼容的最新 WebUI Release。"""
    repo_name = normalize_webui_dist_zip_repo(repo)
    asset_name = (preferred_asset or "").strip() or DEFAULT_WEBUI_DIST_ZIP_ASSET
    pinned_tag = (tag or "").strip()
    bot_commit = (current_commit if current_commit is not None else get_bot_current_commit()).strip()
    if re.fullmatch(r"[0-9a-f]{40}", bot_commit) is None:
        raise WebuiReleaseCompatibilityError("当前 Bot 没有可用于兼容性检查的完整 commit")

    releases = await _fetch_webui_release_list(repo_name, token=token)
    candidates: list[dict[str, Any]] = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        release_tag = str(release.get("tag") or release.get("tag_name") or "").strip()
        if pinned_tag and not release_tags_equivalent(release_tag, pinned_tag):
            continue
        if bool(release.get("prerelease")) or bool(release.get("draft")):
            continue
        version_key = _webui_release_version_key(release_tag)
        if version_key is None or not is_bot_release_style_tag(release_tag):
            continue
        candidates.append({"release": release, "tag": release_tag, "version_key": version_key})

    if pinned_tag and not candidates:
        raise WebuiReleaseCompatibilityError(f"指定 WebUI Release {pinned_tag} 不存在或不是正式版本")
    candidates.sort(key=itemgetter("version_key"), reverse=True)

    saw_pinned_tag = False
    for item in candidates:
        release = item["release"]
        release_tag = item["tag"]
        if pinned_tag:
            saw_pinned_tag = True
        asset_url = _webui_release_asset_url(release, asset_name)
        manifest_url = _webui_release_asset_url(release, "release-manifest.json")
        if not asset_url or not manifest_url:
            logger.debug("[WebUI] Release [{}] missing required assets, skipping", release_tag)
            continue
        try:
            manifest = parse_webui_release_manifest(
                await _fetch_webui_release_manifest(manifest_url, token=token),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[WebUI] Release [{}] manifest 无效，跳过：{}",
                release_tag,
                format_exception_for_log(e),
            )
            continue
        minimum = str(manifest["min_bot_commit"])
        if not await is_bot_commit_compatible(minimum, bot_commit, token=token):
            logger.debug(
                "[WebUI] Release [{}] 要求的 Bot commit [{}] 与当前 commit 不兼容，跳过",
                release_tag,
                minimum,
            )
            continue
        return {
            "tag": release_tag,
            "html_url": str(release.get("html_url") or "").strip(),
            "asset_url": asset_url,
            "body": str(release.get("body") or "").strip(),
            "manifest": manifest,
            "min_bot_commit": minimum,
            "bot_commit": bot_commit,
        }

    if pinned_tag and saw_pinned_tag:
        raise WebuiReleaseCompatibilityError(f"指定 WebUI Release {pinned_tag} 与当前 Bot 不兼容")
    raise WebuiReleaseCompatibilityError("没有找到与当前 Bot 兼容的 WebUI Release")


async def resolve_webui_release_asset_urls(
    repo: str,
    preferred_asset: str = DEFAULT_WEBUI_DIST_ZIP_ASSET,
    tag: str = "",
    *,
    token: str = "",
    current_commit: str | None = None,
) -> list[str]:
    """返回已通过兼容性校验的 WebUI Release 固定资产地址。"""
    release = await resolve_compatible_webui_release(
        repo,
        preferred_asset,
        tag,
        token=token,
        current_commit=current_commit,
    )
    asset_url = str(release.get("asset_url") or "").strip()
    return [asset_url] if asset_url else []


def bot_is_development_build(
    *,
    latest_tag: str,
    current_tag: str = "",
    current_commit: str = "",
) -> bool:
    """是否相对最新 release 为开发构建。"""
    from pallas.core.shared.utils.github_release import release_tags_equivalent

    tag = (latest_tag or "").strip()
    if not tag:
        return False
    if bot_has_release_update(
        latest_tag=tag,
        current_tag=current_tag,
        current_commit=current_commit,
    ):
        return False
    if release_tags_equivalent(current_tag, tag):
        return False
    shas = bot_git_head_and_release_shas(tag)
    if shas is None:
        return not (current_tag or "").strip()
    head_sha, latest_sha = shas
    if head_sha == latest_sha:
        return False
    return bot_git_rev_list_count(f"{latest_sha}..{head_sha}") > 0


class BotGitUpdateError(Exception):
    """控制台 Bot git 更新失败，携带 HTTP 状态码供 API 层映射。"""

    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


async def apply_bot_repository_update(
    *,
    github_token: str = "",
    repo: str = "PallasBot/Pallas-Bot",
    track: str = "release",
    preferred_branch: str = "",
    on_progress: ProgressReporter | None = None,
) -> dict[str, str]:
    """在仓库根目录执行 git 更新。

    ``track=release``：正式版切到最新 release tag；无 exact tag 的开发克隆走 ff-only pull。
    ``track=branch``：始终 pull 跟踪分支 tip（不强制 checkout tag）。

    不在此函数内重启进程。标签切换前自动 stash；分支拉取使用 --autostash。
    """
    from packages.pb_webui.bot_git_manage import apply_bot_git_target

    update_track = normalize_bot_update_track(track)
    mode = "commit" if update_track == "branch" else "release"
    logger.info(
        "[WebUI] Bot 仓库更新开始 repo={} track={} preferred_branch={}",
        repo,
        update_track,
        (preferred_branch or "").strip() or "(auto)",
    )
    return await apply_bot_git_target(
        github_token=github_token,
        repo=repo,
        mode=mode,
        preferred_branch=preferred_branch,
        target_ref="",
        strategy="safe",
        on_progress=on_progress,
    )


async def fetch_latest_bot_release(repo: str = "PallasBot/Pallas-Bot", *, token: str = "") -> dict:
    try:
        data = await fetch_latest_release(
            repo,
            user_agent="Pallas-Bot-PallasWebUI/1.0",
            token=token,
            include_asset_url=False,
            mirror_scope="bot",
        )
        return {"tag": data["tag"], "html_url": data["html_url"], "body": str(data.get("body", "") or "").strip()}
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as first_err:
        try:
            fb = await fetch_latest_release_tag_via_github_web(
                repo,
                token=token,
                user_agent="Pallas-Bot-PallasWebUI/1.0",
                mirror_scope="bot",
            )
            logger.debug(
                "[WebUI] GitHub Release API 不可用，已用 github.com/releases/latest 兜底（Bot）tag={}",
                fb["tag"],
            )
            return {"tag": fb["tag"], "html_url": fb["html_url"], "body": ""}
        except Exception:
            raise first_err from None


async def fetch_latest_webui_release(repo: str, *, token: str = "", asset_name: str = "dist.zip") -> dict:
    asset_clean = (asset_name or "").strip() or "dist.zip"
    try:
        return await fetch_latest_release(
            repo,
            user_agent="Pallas-Bot-PallasWebUI/1.0",
            token=token,
            preferred_asset_name=asset_clean,
            include_asset_url=True,
            mirror_scope="webui",
        )
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as first_err:
        try:
            fb = await fetch_latest_release_tag_via_github_web(
                repo,
                token=token,
                user_agent="Pallas-Bot-PallasWebUI/1.0",
                mirror_scope="webui",
            )
            tag_fb = fb["tag"]
            asset_url_fb = github_release_asset_url(repo, asset_clean, tag_fb)
            logger.debug(
                "[WebUI] GitHub Release API 不可用，已用 github.com/releases/latest 兜底（WebUI）tag={}",
                tag_fb,
            )
            return {"tag": tag_fb, "html_url": fb["html_url"], "asset_url": asset_url_fb, "body": ""}
        except Exception:
            raise first_err from None
