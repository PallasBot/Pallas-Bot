"""社区插件更新日志：CHANGELOG.md 缺失时按 git 提交历史自动生成。"""

from __future__ import annotations

from nonebot import logger

from pallas.console.webui.community_plugin_install import (
    PLUGIN_ID_RE,
    community_plugins_root,
    run_git_command,
)

_GIT_LOG_TIMEOUT_S = 20.0
_GIT_LOG_LIMIT = 30
_FIELD_SEP = "\x1f"


async def generate_community_changelog_from_git(plugin_id: str) -> str | None:
    """读取 local/plugins/<id> 的提交历史，渲染为 Markdown；无本地仓库则返回 None。"""
    pid = (plugin_id or "").strip()
    if not pid or not PLUGIN_ID_RE.fullmatch(pid):
        return None
    plugin_dir = community_plugins_root() / pid
    if not (plugin_dir / ".git").exists():
        return None
    pretty = f"%h{_FIELD_SEP}%ad{_FIELD_SEP}%s"
    try:
        code, out, err = await run_git_command(
            _GIT_LOG_TIMEOUT_S,
            "log",
            f"-n{_GIT_LOG_LIMIT}",
            "--date=short",
            f"--pretty=format:{pretty}",
            cwd=str(plugin_dir),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("社区插件 changelog: git log 失败 plugin={} err={}", pid, exc)
        return None
    if code != 0:
        logger.debug("社区插件 changelog: git log 非零退出 plugin={} err={}", pid, (err or "").strip())
        return None

    rows: list[tuple[str, str, str]] = []
    for line in (out or "").splitlines():
        parts = line.split(_FIELD_SEP, 2)
        if len(parts) != 3:
            continue
        commit, date, subject = (p.strip() for p in parts)
        if commit:
            rows.append((commit, date, subject))
    if not rows:
        return None

    lines = [
        "# 更新日志（自动生成）",
        "",
        "> 该插件未提供 `CHANGELOG.md`，以下内容根据本地 git 提交历史自动生成。",
        "",
    ]
    current_date = ""
    for commit, date, subject in rows:
        if date != current_date:
            if current_date:
                lines.append("")
            lines.append(f"## {date or '未知日期'}")
            current_date = date
        text = subject or "(无提交说明)"
        lines.append(f"- `{commit}` {text}")
    lines.append("")
    return "\n".join(lines)
