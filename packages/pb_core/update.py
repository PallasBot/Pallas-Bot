"""本体 / WebUI / 插件更新：检查与应用（超管私聊）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pallas.core.foundation.command_prefix import extract_command_tail
from pallas.core.foundation.config.repo_settings import merged_repo_settings_upper
from pallas.core.shared.utils.format_exception import format_exception_for_log

UPDATE_COMMAND = "牛牛更新"
UpdateAction = Literal["check", "help", "bot", "webui", "plugins", "all"]
AutoTarget = Literal["bot", "webui", "plugins"]

_AUTO_KEY: dict[AutoTarget, str] = {
    "webui": "pallas_webui_auto_update_enabled",
    "bot": "pallas_bot_auto_update_enabled",
    "plugins": "pallas_plugins_auto_update_enabled",
}

_USAGE = (
    "用法（仅超管私聊）\n"
    f"{UPDATE_COMMAND} — 检查\n"
    f"{UPDATE_COMMAND} 应用|bot|webui|插件 — 应用更新\n"
    f"{UPDATE_COMMAND} 自动 bot|webui|插件 开|关\n"
    f"{UPDATE_COMMAND} 汇报 开|关 · 汇报号 QQ|0"
)

_USAGE_HINT = f"用法：{UPDATE_COMMAND} 帮助"


@dataclass(frozen=True)
class UpdateConfigCommand:
    kind: Literal["auto", "notify", "notify_bot"]
    target: AutoTarget | None = None
    enabled: bool | None = None
    bot_id: int | None = None


def _github_token() -> str:
    env = merged_repo_settings_upper()
    token = (env.get("PALLAS_PROTOCOL_GITHUB_TOKEN") or "").strip()
    if token:
        return token
    try:
        from packages.pb_webui.config import get_pallas_webui_config

        cfg = get_pallas_webui_config()
        return str(getattr(cfg, "pallas_protocol_github_token", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _parse_on_off(token: str) -> bool | None:
    t = (token or "").strip().casefold()
    if t in {"开", "开启", "on", "true", "1", "enable", "enabled"}:
        return True
    if t in {"关", "关闭", "off", "false", "0", "disable", "disabled"}:
        return False
    return None


def _parse_auto_target(token: str) -> AutoTarget | None:
    t = (token or "").strip().casefold()
    if t in {"bot", "本体", "仓库"}:
        return "bot"
    if t in {"webui", "控制台", "前端", "dist"}:
        return "webui"
    if t in {"插件", "plugin", "plugins", "ext"}:
        return "plugins"
    return None


def parse_update_config_command(plain_text: str) -> UpdateConfigCommand | None:
    """解析自动更新 / 汇报相关子命令；非配置类返回 None。"""
    tail = extract_command_tail(plain_text or "", UPDATE_COMMAND).strip()
    if not tail:
        return None
    parts = tail.split()
    head = parts[0].casefold()

    if head in {"自动", "auto"}:
        if len(parts) < 3:
            return None
        target = _parse_auto_target(parts[1])
        enabled = _parse_on_off(parts[2])
        if target is None or enabled is None:
            return None
        return UpdateConfigCommand(kind="auto", target=target, enabled=enabled)

    if head in {"汇报", "通知", "notify", "report"}:
        if len(parts) == 2:
            enabled = _parse_on_off(parts[1])
            if enabled is None:
                return None
            return UpdateConfigCommand(kind="notify", enabled=enabled)
        return None

    if head in {"汇报号", "通知号", "notify_bot", "report_bot"}:
        if len(parts) != 2:
            return None
        raw = parts[1].strip().casefold()
        if raw in {"0", "自动", "auto", "any", "任意"}:
            return UpdateConfigCommand(kind="notify_bot", bot_id=0)
        if not raw.isdigit():
            return None
        return UpdateConfigCommand(kind="notify_bot", bot_id=int(raw))

    return None


def parse_update_action(plain_text: str) -> UpdateAction | None:
    """解析「牛牛更新」应用类参数；无法识别时返回 None。"""
    if parse_update_config_command(plain_text) is not None:
        return None
    tail = extract_command_tail(plain_text or "", UPDATE_COMMAND).strip().casefold()
    if not tail or tail in {"检查", "check", "status", "状态"}:
        return "check"
    if tail in {"帮助", "用法", "help", "usage"}:
        return "help"
    if tail in {"应用", "全部", "all", "apply", "update"}:
        return "all"
    if tail in {"bot", "本体", "仓库"}:
        return "bot"
    if tail in {"webui", "控制台", "前端", "dist"}:
        return "webui"
    if tail in {"插件", "plugin", "plugins", "ext"}:
        return "plugins"
    return None


def update_usage_text() -> str:
    return _USAGE


def _on_off(enabled: bool) -> str:
    return "开" if enabled else "关"


def _fmt_auto_target(label: str, row: dict[str, Any]) -> str:
    enabled = bool(row.get("enabled"))
    last = str(row.get("last_check_result") or "").strip() or "—"
    err = str(row.get("last_error") or "").strip()
    line = f"{label} {_on_off(enabled)} · {last}"
    if err:
        line += f" · 错：{err[:60]}"
    return line


def _summarize_target(label: str, row: dict[str, Any] | None) -> str:
    data = row if isinstance(row, dict) else {}
    result = str(data.get("result") or "").strip() or "—"
    if result == "applied":
        tag = str(data.get("tag") or data.get("message") or "").strip()
        extra = f"：{tag}" if tag else ""
        return f"{label}：已应用{extra}"
    if result == "up_to_date":
        return f"{label}：已是最新"
    if result == "skipped":
        reason = str(data.get("reason") or data.get("skip_reason") or "").strip()
        return f"{label}：跳过" + (f"（{reason}）" if reason else "")
    if result == "failed":
        err = str(data.get("error") or "").strip()
        return f"{label}：失败" + (f"（{err[:160]}）" if err else "")
    if result == "partial":
        updated = data.get("updated") or []
        failed = data.get("failed") or []
        n_ok = len(updated) if isinstance(updated, list) else 0
        n_fail = len(failed) if isinstance(failed, list) else 0
        return f"{label}：部分成功（更新 {n_ok}，失败 {n_fail}）"
    msg = str(data.get("message") or "").strip()
    if msg:
        return f"{label}：{msg}"
    return f"{label}：{result}"


async def format_update_check_text() -> str:
    from packages.pb_webui.config import get_pallas_webui_config
    from packages.pb_webui.manager import (
        DEFAULT_WEBUI_DIST_ZIP_ASSET,
        DEFAULT_WEBUI_DIST_ZIP_REPO,
        bot_has_release_update,
        bot_is_development_build,
        fetch_latest_bot_release,
        get_bot_current_version,
        get_installed_webui_version,
        inspect_bot_deployment,
        normalize_webui_dist_zip_repo,
        resolve_compatible_webui_release,
        webui_has_release_update,
    )
    from packages.pb_webui.webui_auto_update import auto_update_status_payload
    from pallas.console.webui.plugin_update_snapshot import refresh_plugin_update_snapshot
    from pallas.console.webui.update_apply_progress import has_active_update_apply_job

    token = _github_token()
    cfg = get_pallas_webui_config()
    lines: list[str] = []

    current = get_bot_current_version()
    current_tag = str(current.get("tag") or "").strip()
    current_commit = str(current.get("commit") or "").strip()
    bot_now = current_tag or current_commit or "unknown"
    bot_bits = [f"当前 {bot_now}"]
    try:
        latest = await fetch_latest_bot_release("PallasBot/Pallas-Bot", token=token)
        latest_tag = str(latest.get("tag") or "").strip()
        if latest_tag:
            bot_bits.append(f"最新 {latest_tag}")
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
            bot_bits.append("有更新")
        elif dev_build:
            bot_bits.append("开发构建")
        else:
            bot_bits.append("已是最新")
    except Exception as exc:  # noqa: BLE001
        bot_bits.append(f"检查失败：{format_exception_for_log(exc)}")

    deploy = inspect_bot_deployment()
    mode = str(deploy.get("deployment_mode") or "").strip() or "unknown"
    bot_bits.append(mode if mode == "release_tag" else f"{mode}不可自动apply")
    lines.append("【Bot】" + " · ".join(bot_bits))

    installed = get_installed_webui_version()
    webui_current = str(installed.get("tag") or "").strip() or "unknown"
    web_bits = [f"当前 {webui_current}"]

    repo = normalize_webui_dist_zip_repo(
        str(getattr(cfg, "pallas_webui_dist_zip_repo", "") or DEFAULT_WEBUI_DIST_ZIP_REPO)
    )
    asset = str(getattr(cfg, "pallas_webui_dist_zip_asset", "") or DEFAULT_WEBUI_DIST_ZIP_ASSET)
    requested_tag = str(getattr(cfg, "pallas_webui_dist_zip_tag", "") or "").strip()
    try:
        web_latest = await resolve_compatible_webui_release(repo, asset, requested_tag, token=token)
        web_tag = str(web_latest.get("tag") or "").strip()
        if web_tag:
            web_bits.append(f"最新 {web_tag}")
        if webui_has_release_update(latest_tag=web_tag, current_tag=webui_current):
            web_bits.append("有更新")
        else:
            web_bits.append("已是最新或无法比较")
    except Exception as exc:  # noqa: BLE001
        web_bits.append(f"检查失败：{format_exception_for_log(exc)}")
    lines.append("【WebUI】" + " · ".join(web_bits))

    try:
        snap = await refresh_plugin_update_snapshot()
        official = snap.get("official") if isinstance(snap.get("official"), dict) else {}
        community = snap.get("community") if isinstance(snap.get("community"), dict) else {}
        off_n = sum(1 for e in official.values() if isinstance(e, dict) and e.get("has_update") is True)
        com_n = sum(1 for e in community.values() if isinstance(e, dict) and e.get("has_update") is True)
        lines.append(f"【插件】待更新 官方 {off_n} · 社区 {com_n}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"【插件】快照失败：{format_exception_for_log(exc)}")

    auto = auto_update_status_payload(cfg)
    lines.append("【自动更新】")
    lines.extend([
        _fmt_auto_target("WebUI", auto.get("webui") or {}),
        _fmt_auto_target("Bot", auto.get("bot") or {}),
        _fmt_auto_target("插件", auto.get("plugins") or {}),
    ])
    notify_on = bool(auto.get("notify_superusers"))
    notify_bot = int(auto.get("notify_bot_id") or 0)
    notify_bot_label = "任选" if notify_bot <= 0 else str(notify_bot)
    lines.append(f"汇报 {_on_off(notify_on)} · 号 {notify_bot_label}")
    if has_active_update_apply_job():
        lines.append("有更新任务进行中")
    lines.append(_USAGE_HINT)
    return "\n".join(lines)


async def _apply_bot() -> dict[str, Any]:
    from packages.pb_webui.manager import BotGitUpdateError
    from packages.pb_webui.webui_auto_update import _run_bot_target
    from pallas.console.cli.update_ops import apply_bot_update

    out = await _run_bot_target(force=True)
    if isinstance(out, dict) and out.get("result") == "skipped":
        reason = str(out.get("reason") or "")
        # 自动更新只接受干净 release_tag；超管手动仍可走完整 apply
        if reason.startswith("deploy:"):
            try:
                data = await apply_bot_update(restart=True)
                return {
                    "result": "applied",
                    "tag": str(data.get("tag") or "").strip(),
                    "message": str(data.get("message") or "").strip(),
                    "restart_scheduled": bool(data.get("restart_scheduled")),
                }
            except BotGitUpdateError as exc:
                return {"result": "failed", "error": exc.detail}
    return out if isinstance(out, dict) else {"result": "failed", "error": "unknown"}


async def _apply_webui() -> dict[str, Any]:
    from packages.pb_webui.webui_auto_update import _run_webui_target

    out = await _run_webui_target(force=True)
    return out if isinstance(out, dict) else {"result": "failed", "error": "unknown"}


async def _apply_plugins() -> dict[str, Any]:
    from packages.pb_webui.webui_auto_update import _run_plugins_target

    out = await _run_plugins_target(force=True)
    return out if isinstance(out, dict) else {"result": "failed", "error": "unknown"}


def _plugins_extra(out: dict[str, Any]) -> str:
    from packages.pb_webui.webui_auto_update import format_plugin_update_item

    bits: list[str] = []
    updated = out.get("updated")
    if isinstance(updated, list) and updated:
        rows = [f"- {format_plugin_update_item(item)}" for item in updated[:12]]
        if len(updated) > 12:
            rows.append(f"- 其余 {len(updated) - 12} 个")
        bits.append("已更新：\n" + "\n".join(rows))
    failed = out.get("failed")
    if isinstance(failed, list) and failed:
        parts: list[str] = []
        for item in failed[:6]:
            if isinstance(item, dict):
                parts.append(f"{item.get('id')}:{item.get('error')}")
            else:
                parts.append(str(item))
        bits.append("失败：" + "、".join(parts))
    if out.get("restart_scheduled"):
        bits.append("后续：已安排重启 Bot")
    return ("\n" + "\n".join(bits)) if bits else ""


def apply_update_config_command(cmd: UpdateConfigCommand) -> str:
    """写入 pb_webui 自动更新相关配置。"""
    from pallas.console.webui.plugin_api import apply_plugin_config_patch

    labels = {"webui": "WebUI", "bot": "Bot", "plugins": "插件"}
    try:
        if cmd.kind == "auto":
            if cmd.target is None or cmd.enabled is None:
                return update_usage_text()
            key = _AUTO_KEY[cmd.target]
            apply_plugin_config_patch("pb_webui", {key: cmd.enabled})
            return f"已设置{labels[cmd.target]}自动更新：{_on_off(cmd.enabled)}"

        if cmd.kind == "notify":
            if cmd.enabled is None:
                return update_usage_text()
            apply_plugin_config_patch(
                "pb_webui",
                {"pallas_auto_update_notify_superusers": cmd.enabled},
            )
            return f"已设置自动更新汇报超管：{_on_off(cmd.enabled)}"

        if cmd.bot_id is None:
            return update_usage_text()
        apply_plugin_config_patch(
            "pb_webui",
            {"pallas_auto_update_notify_bot_id": int(cmd.bot_id)},
        )
        if int(cmd.bot_id) <= 0:
            return "已设置汇报发送号：任选当前在线的牛"
        return f"已设置汇报发送号：{int(cmd.bot_id)}"
    except Exception as exc:  # noqa: BLE001
        return f"配置失败：{format_exception_for_log(exc)}"


async def apply_update_action(action: UpdateAction) -> str:
    """应用或检查更新。"""
    from pallas.console.webui.update_apply_progress import has_active_update_apply_job

    if action == "help":
        return update_usage_text()

    if action == "check":
        return await format_update_check_text()

    if has_active_update_apply_job():
        return "已有更新任务在进行，请稍后再试（或到 WebUI 查看进度）。"

    try:
        if action == "all":
            webui = await _apply_webui()
            plugins = await _apply_plugins()
            bot = await _apply_bot()
            lines = [
                "全部更新结束",
                _summarize_target("WebUI", webui),
                _summarize_target("插件", plugins) + _plugins_extra(plugins),
                _summarize_target("Bot", bot),
            ]
            return "\n".join(lines)

        if action == "webui":
            return _summarize_target("WebUI", await _apply_webui())

        if action == "plugins":
            out = await _apply_plugins()
            return "【插件更新】\n" + _summarize_target("插件", out) + _plugins_extra(out)

        out = await _apply_bot()
        return _summarize_target("Bot", out)
    except Exception as exc:  # noqa: BLE001
        return f"更新失败：{format_exception_for_log(exc)}"
