"""控制台静态资源：默认目录 data/pallas_webui/public，可选 zip 直链下载解压。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx
from nonebot import logger

from src.common.paths import plugin_data_dir
from src.common.utils.format_exception import format_exception_for_log
from src.common.utils.github_release import (
    fetch_latest_release,
    fetch_latest_release_tag_via_github_web,
    github_auth_headers,
    github_release_api_url,
    github_release_asset_url,
    github_release_asset_url_candidates,
    github_request_ssl_env,
)
from src.common.utils.stream_download import (
    StreamDownloadProgress,
    format_download_byte_size,
    sync_stream_download_to_file,
)


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
                        "Pallas-Bot 控制台: GitHub Release API 请求异常（将尝试直链）api={} err={}",
                        api,
                        format_exception_for_log(e),
                    )
                    continue
                if resp.status_code != 200:
                    logger.debug(
                        "Pallas-Bot 控制台: GitHub Release API 非 200（将尝试直链）status={} api={}",
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


def webui_public_path() -> Path:
    return plugin_data_dir("pallas_webui") / "public"


def check_webui_exists(path: Path) -> bool:
    return (path / "index.html").is_file()


def _resolved_extract_root(archive_dir: Path) -> Path:
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
            "Pallas-Bot 控制台: WebUI dist 下载进度 {}%（{}/{}）",
            ev["milestone_percent"],
            format_download_byte_size(ev["received"]),
            format_download_byte_size(ev["total"]),
        )
    elif ev["event"] == "unknown_step":
        logger.info(
            "Pallas-Bot 控制台: WebUI dist 已下载 {}（服务器未提供文件大小）",
            format_download_byte_size(ev["received"]),
        )
    elif ev["event"] == "complete":
        if ev["total"] is not None:
            logger.info(
                "Pallas-Bot 控制台: WebUI dist 下载完成 {} / {}",
                format_download_byte_size(ev["received"]),
                format_download_byte_size(ev["total"]),
            )
        elif ev["received"] > 0:
            logger.info(
                "Pallas-Bot 控制台: WebUI dist 下载完成 {}",
                format_download_byte_size(ev["received"]),
            )


def _sync_download_webui_zip(url: str, dest: Path, *, follow_redirects: bool) -> None:
    sync_stream_download_to_file(
        url,
        dest,
        follow_redirects=follow_redirects,
        timeout=httpx.Timeout(300.0, connect=60.0),
        on_progress=_webui_download_progress_log,
    )


async def download_and_extract_dist_zip(public_dir: Path, url: str, *, follow_redirects: bool = True) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    preview = url if len(url) <= 200 else url[:197] + "..."
    logger.info("Pallas-Bot 控制台: 正在下载 WebUI dist {}", preview)

    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = Path(tmp_zip.name)
    tmp_zip.close()

    try:
        await asyncio.to_thread(_sync_download_webui_zip, url, zip_path, follow_redirects=follow_redirects)
        await asyncio.to_thread(_sync_extract_dist_zip_file, zip_path, public_dir)
        logger.info("Pallas-Bot 控制台: 已解压 dist 到 data/pallas_webui/public")
    finally:
        await asyncio.to_thread(_unlink_ignore_missing, zip_path)

    return True


def webui_version_path() -> Path:
    return plugin_data_dir("pallas_webui") / "version.json"


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


_BOT_ROOT = Path(__file__).resolve().parents[3]


def get_bot_current_version() -> dict:
    import subprocess

    root = _BOT_ROOT
    tag = ""
    commit = ""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    return {"tag": tag, "commit": commit}


def bot_has_release_update(
    *,
    latest_tag: str,
    current_tag: str = "",
    current_commit: str = "",
) -> bool:
    """是否落后于 GitHub 最新 release（开发超前 commit 不视为可更新）。"""
    from src.common.utils.github_release import release_tags_equivalent

    tag = (latest_tag or "").strip()
    if not tag:
        return False
    if release_tags_equivalent(current_tag, tag):
        return False
    root = _BOT_ROOT
    git_dir = root / ".git"
    if not git_dir.exists():
        cur = (current_tag or "").strip()
        return bool(cur) and not release_tags_equivalent(cur, tag)

    def _git_rev_parse(ref: str) -> str:
        import subprocess

        return subprocess.check_output(
            ["git", "rev-parse", ref],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8.0,
        ).strip()

    def _git_rev_list_count(revision_range: str) -> int:
        import subprocess

        out = subprocess.check_output(
            ["git", "rev-list", "--count", revision_range],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8.0,
        ).strip()
        return int(out) if out.isdigit() else 0

    try:
        latest_sha = _git_rev_parse(f"{tag}^{{commit}}")
        head_sha = _git_rev_parse("HEAD")
    except Exception:  # noqa: BLE001
        cur = (current_tag or "").strip()
        return bool(cur) and not release_tags_equivalent(cur, tag)
    if latest_sha == head_sha:
        return False
    try:
        behind = _git_rev_list_count(f"{head_sha}..{latest_sha}")
    except Exception:  # noqa: BLE001
        return False
    return behind > 0


def get_pallas_bot_version_for_health() -> str:
    """供 ``/health`` 的 ``pallas_bot``：优先环境变量（镜像注入）、git describe，其次已安装发行版号，最后 pyproject。"""
    import importlib.metadata
    import subprocess
    import tomllib

    env = (os.environ.get("PALLAS_BOT_VERSION") or os.environ.get("PALLAS_VERSION") or "").strip()
    if env:
        return env
    root = _BOT_ROOT
    try:
        desc = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3.0,
        ).strip()
        if desc:
            return desc
    except Exception:  # noqa: BLE001
        pass
    try:
        v = importlib.metadata.version("pallas-bot")
        if v.strip():
            return v.strip()
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        pyproject = root / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "")).strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


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
) -> dict[str, str]:
    """在仓库根目录执行 git 更新：发布标签部署切到新 tag；开发克隆走 ff-only pull。

    不在此函数内重启进程。标签切换要求工作区干净；分支拉取使用 --autostash。
    """
    root = _BOT_ROOT
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    async def git(*args: str, cmd_timeout_s: float = 180.0) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
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
            msg = "git 操作超时，请检查网络或稍后在命令行重试"
            raise BotGitUpdateError(msg, status_code=504) from None
        out = out_b.decode(errors="replace").strip() if out_b else ""
        err = err_b.decode(errors="replace").strip() if err_b else ""
        code = int(proc.returncode or 0)
        return code, out, err

    rc, out, err = await git("rev-parse", "--is-inside-work-tree")
    if rc != 0 or out != "true":
        raise BotGitUpdateError(
            "当前运行目录不是 git 工作副本（例如 Docker 仅含镜像内文件）。请使用 docker compose pull "
            "或按文档手动部署更新。",
            status_code=400,
        )

    try:
        latest = await fetch_latest_bot_release(repo, token=github_token)
    except asyncio.CancelledError:
        raise
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as e:
        raise BotGitUpdateError(
            f"无法从 GitHub 获取最新发布信息：{format_exception_for_log(e)}",
            status_code=502,
        ) from e

    latest_tag = str(latest.get("tag", "") or "").strip()
    if not latest_tag:
        raise BotGitUpdateError("GitHub 未返回可用的发布标签。", status_code=502)

    logger.info("Pallas-Bot 控制台: Bot 仓库更新开始 repo={} target_tag={}", repo, latest_tag)

    rc, _, fetch_err = await git("fetch", "origin", "--tags", cmd_timeout_s=300.0)
    if rc != 0:
        detail = fetch_err or "(无 stderr)"
        raise BotGitUpdateError(f"git fetch 失败：{detail}", status_code=502)

    tag_peel = f"{latest_tag}^{{}}"
    rc_peel, _, _ = await git("rev-parse", "-q", "--verify", tag_peel)
    rc_tag, _, _ = await git("rev-parse", "-q", "--verify", f"refs/tags/{latest_tag}")
    if rc_peel != 0 and rc_tag != 0:
        raise BotGitUpdateError(
            f"fetch 后仍无法解析标签 {latest_tag}，请确认远端存在该发布。",
            status_code=400,
        )
    detach_ref = tag_peel if rc_peel == 0 else f"refs/tags/{latest_tag}"

    current = get_bot_current_version()
    current_tag = str(current.get("tag", "") or "").strip()

    if current_tag and current_tag == latest_tag:
        commit = str(current.get("commit", "") or "").strip()
        logger.info("Pallas-Bot 控制台: Bot 已处于目标标签 {}", latest_tag)
        return {
            "tag": latest_tag,
            "message": f"已处于发布标签 {latest_tag}（{commit or 'commit 未知'}），无需更新。",
        }

    rc, porcelain, _ = await git("status", "--porcelain")
    dirty = bool(porcelain.strip())

    if current_tag:
        if dirty:
            raise BotGitUpdateError(
                "工作区不干净（存在未提交修改或未跟踪冲突风险）。切换到新发布标签前请先处理本地改动，"
                "或改用命令行按文档执行 git pull / stash。",
                status_code=409,
            )
        rc_co, _, err_co = await git("checkout", "--detach", detach_ref)
        if rc_co != 0:
            raise BotGitUpdateError(
                f"切换到标签 {latest_tag} 失败：{err_co or '(无 stderr)'}",
                status_code=400,
            )
        logger.info("Pallas-Bot 控制台: Bot 已 checkout 至标签 {}", latest_tag)
    else:
        rc_u, upstream_out, _ = await git("rev-parse", "--abbrev-ref", "@{u}")
        if rc_u == 0 and upstream_out:
            rc_p, _, err_p = await git("pull", "--ff-only", "--autostash")
            if rc_p != 0:
                raise BotGitUpdateError(
                    f"git pull --ff-only 失败（已配置上游 {upstream_out}）：{err_p or '(无 stderr)'}",
                    status_code=400,
                )
            logger.info("Pallas-Bot 控制台: Bot 已通过 pull --ff-only 更新（上游 {}）", upstream_out)
        else:
            rc_sym, sym_out, _ = await git("symbolic-ref", "-q", "refs/remotes/origin/HEAD")
            def_branch = "master"
            if rc_sym == 0 and sym_out.startswith("refs/remotes/origin/"):
                def_branch = sym_out.rsplit("/", maxsplit=1)[-1]
            else:
                for cand in ("master", "main"):
                    rc_ob, _, _ = await git("rev-parse", "-q", "--verify", f"origin/{cand}")
                    if rc_ob == 0:
                        def_branch = cand
                        break
            rc_p, _, err_p = await git("pull", "--ff-only", "--autostash", "origin", def_branch)
            if rc_p != 0:
                raise BotGitUpdateError(
                    f"git pull --ff-only --autostash origin {def_branch} 失败：{err_p or '(无 stderr)'}",
                    status_code=400,
                )
            logger.info(
                "Pallas-Bot 控制台: Bot 已通过 pull --ff-only 更新（origin/{}）",
                def_branch,
            )

    after = get_bot_current_version()
    new_tag = str(after.get("tag", "") or "").strip()
    new_commit = str(after.get("commit", "") or "").strip()
    display = new_tag or new_commit or latest_tag
    return {
        "tag": display,
        "message": f"仓库已更新（{display}）。请重启 Bot 进程后加载新代码。",
    }


async def fetch_latest_bot_release(repo: str = "PallasBot/Pallas-Bot", *, token: str = "") -> dict:
    try:
        data = await fetch_latest_release(
            repo,
            user_agent="Pallas-Bot-PallasWebUI/1.0",
            token=token,
            include_asset_url=False,
        )
        return {"tag": data["tag"], "html_url": data["html_url"], "body": str(data.get("body", "") or "").strip()}
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as first_err:
        try:
            fb = await fetch_latest_release_tag_via_github_web(
                repo,
                token=token,
                user_agent="Pallas-Bot-PallasWebUI/1.0",
            )
            logger.debug(
                "Pallas-Bot 控制台: GitHub Release API 不可用，已用 github.com/releases/latest 兜底（Bot）tag={}",
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
        )
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as first_err:
        try:
            fb = await fetch_latest_release_tag_via_github_web(
                repo,
                token=token,
                user_agent="Pallas-Bot-PallasWebUI/1.0",
            )
            tag_fb = fb["tag"]
            asset_url_fb = github_release_asset_url(repo, asset_clean, tag_fb)
            logger.debug(
                "Pallas-Bot 控制台: GitHub Release API 不可用，已用 github.com/releases/latest 兜底（WebUI）tag={}",
                tag_fb,
            )
            return {"tag": tag_fb, "html_url": fb["html_url"], "asset_url": asset_url_fb, "body": ""}
        except Exception:
            raise first_err from None
