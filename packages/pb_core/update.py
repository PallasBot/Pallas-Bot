"""本体更新检查摘要。"""

from __future__ import annotations

from pallas.core.shared.utils.format_exception import format_exception_for_log


async def format_update_check_text() -> str:
    from packages.pb_webui.config import get_config as get_webui_config
    from packages.pb_webui.manager import (
        bot_has_release_update,
        bot_is_development_build,
        fetch_latest_bot_release,
        get_bot_current_version,
        inspect_bot_deployment,
    )

    plugin_config = get_webui_config()
    github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
    current = get_bot_current_version()
    current_tag = str(current.get("tag") or "").strip()
    current_commit = str(current.get("commit") or "").strip()
    lines = [f"当前：{current_tag or current_commit or 'unknown'}"]

    try:
        latest = await fetch_latest_bot_release("PallasBot/Pallas-Bot", token=github_token)
        latest_tag = str(latest.get("tag") or "").strip()
    except Exception as exc:  # noqa: BLE001
        lines.append(f"检查失败：{format_exception_for_log(exc)}")
        return "\n".join(lines)

    lines.append(f"最新发布：{latest_tag or 'unknown'}")
    has_update = bot_has_release_update(
        latest_tag=latest_tag,
        current_tag=current_tag,
        current_commit=current_commit,
    )
    dev_build = bot_is_development_build(
        latest_tag=latest_tag,
        current_tag=current_tag,
        current_commit=current_commit,
    )
    if has_update:
        lines.append("结论：有新版本可更新。")
    elif dev_build:
        lines.append("结论：开发构建，可能领先于最新 release。")
    else:
        lines.append("结论：已是最新 release。")

    deploy = inspect_bot_deployment()
    mode = str(deploy.get("deployment_mode") or "").strip()
    if mode:
        lines.append(f"部署：{mode}")
    lines.append("应用更新请用 WebUI 或 pallas update bot；群内仅只读检查。")
    return "\n".join(lines)
