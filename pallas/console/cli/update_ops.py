"""Bot / WebUI 在线更新。"""

from __future__ import annotations

from nonebot import logger

from packages.pb_webui.manager import DEFAULT_WEBUI_DIST_ZIP_ASSET, DEFAULT_WEBUI_DIST_ZIP_REPO
from pallas.core.foundation.config.repo_settings import merged_repo_settings_upper
from pallas.core.shared.utils.format_exception import format_exception_for_log


class WebuiUpdateError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def webui_update_settings_from_repo() -> dict[str, str]:
    env = merged_repo_settings_upper()
    return {
        "repo": (env.get("PALLAS_WEBUI_DIST_ZIP_REPO") or DEFAULT_WEBUI_DIST_ZIP_REPO).strip(),
        "asset": (env.get("PALLAS_WEBUI_DIST_ZIP_ASSET") or DEFAULT_WEBUI_DIST_ZIP_ASSET).strip(),
        "tag": (env.get("PALLAS_WEBUI_DIST_ZIP_TAG") or "").strip(),
        "github_token": (env.get("PALLAS_PROTOCOL_GITHUB_TOKEN") or "").strip(),
    }


async def apply_webui_dist_update(
    *,
    repo: str | None = None,
    asset: str | None = None,
    tag: str | None = None,
    github_token: str | None = None,
    refresh_runtime_meta: bool = False,
) -> dict[str, str]:
    from packages.pb_webui.manager import (
        download_and_extract_dist_zip,
        fetch_latest_webui_release,
        get_webui_dist_version,
        resolve_github_release_asset_urls,
        save_installed_webui_version,
        webui_public_path,
    )

    defaults = webui_update_settings_from_repo()
    repo_name = (repo if repo is not None else defaults["repo"]).strip()
    asset_name = (asset if asset is not None else defaults["asset"]).strip() or "dist.zip"
    tag_name = (tag if tag is not None else defaults["tag"]).strip()
    token = github_token if github_token is not None else defaults["github_token"]
    public = webui_public_path()

    logger.info(
        "Pallas CLI: WebUI 在线更新开始 repo={} asset={} tag={}",
        repo_name,
        asset_name,
        tag_name or "(latest)",
    )
    url_candidates = await resolve_github_release_asset_urls(
        repo_name,
        asset_name,
        tag_name,
        token=token,
    )
    if not url_candidates:
        raise WebuiUpdateError("未找到可用的下载地址")

    errors: list[str] = []
    succeeded_url = ""
    for i, candidate in enumerate(url_candidates, start=1):
        short = candidate if len(candidate) <= 160 else candidate[:157] + "..."
        logger.info("Pallas CLI: WebUI 更新尝试 {}/{} {}", i, len(url_candidates), short)
        try:
            await download_and_extract_dist_zip(public, candidate)
            succeeded_url = candidate
            errors.clear()
            break
        except Exception as e:  # noqa: BLE001
            err_msg = format_exception_for_log(e)
            errors.append(f"{candidate} -> {err_msg}")
            logger.warning("Pallas CLI: WebUI 下载/解压失败 {}", err_msg)
    if errors:
        raise WebuiUpdateError("下载失败: " + " | ".join(errors))

    try:
        info = await fetch_latest_webui_release(repo_name, token=token, asset_name=asset_name)
        new_tag = str(info.get("tag", "") or tag_name).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Pallas CLI: 获取 WebUI release 元数据失败 tag={} err={}",
            tag_name or "(空)",
            format_exception_for_log(e),
        )
        new_tag = tag_name

    save_installed_webui_version(new_tag, succeeded_url)
    try:
        dist_ver = get_webui_dist_version()
    except Exception:  # noqa: BLE001
        dist_ver = ""
    effective_version = (dist_ver or "").strip() or new_tag or "unknown"

    if refresh_runtime_meta:
        from packages.pb_webui.api import invalidate_health_snapshot
        from packages.pb_webui.console_meta_store import get_console_meta, set_console_meta

        set_console_meta({**get_console_meta(), "version": effective_version})
        invalidate_health_snapshot()

    logger.info("Pallas CLI: WebUI 已更新至 {}（发布 tag: {}）", effective_version, new_tag)
    return {
        "tag": new_tag,
        "version": effective_version,
        "message": "更新成功",
    }


async def apply_bot_update(
    *,
    github_token: str | None = None,
    repo: str = "PallasBot/Pallas-Bot",
    restart: bool = False,
) -> dict[str, str | bool]:
    from packages.pb_webui.manager import BotGitUpdateError, apply_bot_repository_update
    from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
    from pallas.console.cli.extension_ops import append_restart_note

    defaults = webui_update_settings_from_repo()
    token = defaults["github_token"] if github_token is None else github_token
    try:
        result = await apply_bot_repository_update(github_token=token, repo=repo)
    except BotGitUpdateError:
        raise
    scheduled = False
    if restart and bot_lifecycle_available():
        scheduled = schedule_bot_restart(delay_s=3.0)
    out = dict(result)
    out["restart_scheduled"] = scheduled
    if restart:
        out["message"] = append_restart_note(str(out.get("message") or ""), scheduled=scheduled)
    return out
