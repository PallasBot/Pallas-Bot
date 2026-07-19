"""社区插件安装目标解析（WebUI / CLI 共用）。"""

from __future__ import annotations

from pallas.console.webui.community_plugin_install import (
    CommunityPluginInstallError,
    validate_git_repository,
    validate_plugin_id,
)


async def resolve_community_plugin_target(
    plugin_id: str,
    *,
    repository_url: str | None = None,
    ref: str = "main",
) -> tuple[str, str, str]:
    pid = validate_plugin_id(plugin_id)
    repo = (repository_url or "").strip()
    branch = (ref or "main").strip() or "main"
    if not repo:
        from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe

        index = await load_community_plugin_index_safe()
        for entry in index.get("plugins") or []:
            if str(entry.get("plugin_id")) == pid:
                repo = str(entry.get("repository_url") or "").strip()
                branch = str(entry.get("ref") or branch).strip() or "main"
                break
    if not repo:
        raise CommunityPluginInstallError("缺少 repository_url，且索引中无该插件")
    return pid, validate_git_repository(repo), branch
