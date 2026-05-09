from enum import StrEnum

from nonebot import get_loaded_plugins

from .config import Config
from .plugin_manager import find_plugin, plugin_display_name
from .visibility import load_help_hidden_plugins


class HelpMarkdownIssue(StrEnum):
    """帮助 Markdown 生成结果（供 handler 分支，避免解析正文）。"""

    OK = "ok"
    PLUGIN_NOT_FOUND = "plugin_not_found"
    METADATA_MISSING = "metadata_missing"
    FUNCTION_NOT_FOUND = "function_not_found"


def generate_plugins_markdown(
    plugin_config: Config, show_ignored: bool = False, ignored_plugins: list | None = None
) -> str:
    """生成一级菜单。"""
    plugins = get_loaded_plugins()

    if show_ignored:
        filtered_plugins = [plugin for plugin in plugins if plugin.name]
    else:
        ignored_plugins = ignored_plugins or (plugin_config.ignored_plugins if plugin_config else [])
        hidden_plugins = set(load_help_hidden_plugins())
        filtered_plugins = [
            plugin
            for plugin in plugins
            if plugin.name and plugin.name not in ignored_plugins and plugin.name not in hidden_plugins
        ]

    n = len(filtered_plugins)
    title = "# 牛牛帮助" if not show_ignored else "# 牛牛帮助（超级用户）"
    markdown_content = f"{title}\n\n"
    markdown_content += (
        f"下面是当前已加载的 **{n}** 个插件，按展示名称排序。表格里「状态」表示在本群（或私聊）下是否可用。\n\n"
    )

    markdown_content += "| 序号 | 插件名称 | 状态 | 简介 |\n"
    markdown_content += "|------|----------|------|------|\n"

    sorted_plugins = sorted(filtered_plugins, key=lambda p: plugin_display_name(p))

    for index, plugin in enumerate(sorted_plugins, 1):
        plugin_name = plugin_display_name(plugin)

        if plugin.metadata:
            metadata = plugin.metadata
            description = metadata.description or "暂无描述"
        else:
            description = "暂无描述"

        status_placeholder = "{status}"

        markdown_content += f"| {index} | {plugin_name} | {status_placeholder} | {description} |\n"

    if show_ignored:
        markdown_content += "\n> 本视图包含通常被隐藏的插件，仅超级用户在私聊下可见。\n"

    # 一律用「」表示命令，避免 pillowmd 行内代码与正文混排导致基线错位
    markdown_content += "\n## 下一步怎么做\n\n"
    markdown_content += (
        "1. **看某个插件的详情**：发「牛牛帮助」，空一格后接 **序号** 或 **插件名**。\n"
        "   （插件名可用中文展示名，或与包名一致的英文名。）\n"
    )
    markdown_content += (
        "2. **开 / 关插件**（群里需要管理员或超管）：「牛牛开启 〈插件名或序号〉」「牛牛关闭 〈插件名或序号〉」。\n"
    )
    markdown_content += "3. **一次开关全部插件**（需管理员或超管）：「牛牛开启全部功能」「牛牛关闭全部功能」。\n\n"
    markdown_content += "**示例**（数字表示上表序号，换成你的目标即可）\n\n"
    markdown_content += "- 打开上表第 1 个插件：「牛牛帮助 1」\n"
    markdown_content += "- 按中文名打开：「牛牛帮助 帮助系统」\n"
    return markdown_content


def generate_plugin_functions_markdown(
    plugin_name: str, plugin_status: str | None = None
) -> tuple[str, HelpMarkdownIssue]:
    """生成二级菜单。"""
    target_plugin = find_plugin(plugin_name)
    if not target_plugin:
        text = (
            f"# 未找到插件\n\n"
            f"没有找到与「{plugin_name}」对应的插件。\n\n"
            f"请发「牛牛帮助」回到总列表，核对序号或名称后再试。"
        )
        return text, HelpMarkdownIssue.PLUGIN_NOT_FOUND

    plugin_name_display = plugin_display_name(target_plugin)
    markdown_content = f"# {plugin_name_display}"

    if plugin_status:
        status_display = "✅ 已启用" if plugin_status == "✅ 启用" else "⛔ 已禁用"
        markdown_content += f"（{status_display}）\n\n"

        action_hint = "关闭" if plugin_status == "✅ 启用" else "开启"
        verb = "停用" if plugin_status == "✅ 启用" else "启用"
        markdown_content += f"要{verb}本插件，可发：「牛牛{action_hint} {plugin_name_display}」\n\n"
    else:
        markdown_content += "\n\n"

    if target_plugin.metadata:
        metadata = target_plugin.metadata
        description = metadata.description or "暂无描述"
        usage = metadata.usage or "暂无说明"
        markdown_content += "## 说明\n\n"
        markdown_content += f"{description}\n\n"
        markdown_content += "## 插件内用法\n\n"
        markdown_content += f"{usage}\n\n"

        if hasattr(metadata, "extra") and metadata.extra:
            menu_data = metadata.extra.get("menu_data", [])
            if menu_data:
                markdown_content += "## 本插件功能一览\n\n"
                markdown_content += "| 序号 | 功能 | 简介 |\n"
                markdown_content += "|------|------|------|\n"
                for i, item in enumerate(menu_data, 1):
                    func_name = item.get("func", f"未命名功能 {i}")
                    brief_des = item.get("brief_des", "暂无简介")
                    markdown_content += f"| {i} | {func_name} | {brief_des} |\n"
                markdown_content += "\n### 查看功能详情\n\n"
                markdown_content += f"**示例**（当前插件为「{plugin_name_display}」）\n\n"
                markdown_content += f"- 「牛牛帮助 {plugin_name_display} 1」→ 打开表中第 1 条功能的详情页\n"
                if len(menu_data) > 1:
                    markdown_content += f"- 「牛牛帮助 {plugin_name_display} 2」→ 第 2 条\n"

            else:
                markdown_content += "本插件未在元数据里登记「功能列表」，只有上面的总说明。\n\n"
        else:
            markdown_content += "本插件未在元数据里登记「功能列表」，只有上面的总说明。\n\n"
    else:
        markdown_content += "本插件没有可用的元数据说明。\n\n"

    markdown_content += "---\n\n**返回总列表**：发「牛牛帮助」即可。\n"
    return markdown_content, HelpMarkdownIssue.OK


def generate_function_detail_markdown(plugin_name: str, function_name: str) -> tuple[str, HelpMarkdownIssue]:
    """生成三级菜单。"""
    target_plugin = find_plugin(plugin_name)
    if not target_plugin:
        text = f"# 未找到插件\n\n没有找到与「{plugin_name}」对应的插件。\n\n请发「牛牛帮助」回到总列表后再试。"
        return text, HelpMarkdownIssue.PLUGIN_NOT_FOUND

    if not target_plugin.metadata or not hasattr(target_plugin.metadata, "extra"):
        pd = plugin_display_name(target_plugin)
        text = f"# 暂无详情\n\n插件「{pd}」没有可供展示的元数据，因此无法打开本条功能的详细页。"
        return text, HelpMarkdownIssue.METADATA_MISSING

    metadata = target_plugin.metadata
    menu_data = metadata.extra.get("menu_data", []) if metadata.extra else []

    target_function = None
    target_index = -1

    if function_name.isdigit():
        index = int(function_name) - 1
        if 0 <= index < len(menu_data):
            target_function = menu_data[index]
            target_index = index + 1
    else:
        for index, item in enumerate(menu_data):
            func = item.get("func", "")
            if func.lower() == function_name.lower():
                target_function = item
                target_index = index + 1
                break

        if not target_function:
            for index, item in enumerate(menu_data):
                func = item.get("func", "")
                if function_name.lower() in func.lower():
                    target_function = item
                    target_index = index + 1
                    break

    if not target_function:
        pd = plugin_display_name(target_plugin)
        text = (
            f"# 未找到该功能\n\n"
            f"在插件「{pd}」下没有找到与「{function_name}」对应的功能项。\n\n"
            f"请发「牛牛帮助 {pd}」先打开功能列表，确认序号或名称。"
        )
        return text, HelpMarkdownIssue.FUNCTION_NOT_FOUND

    func_name = target_function.get("func", "未命名功能")
    plugin_name_display = plugin_display_name(target_plugin)
    markdown_content = f"# {plugin_name_display} · {func_name}\n\n"

    markdown_content += "| 项 | 内容 |\n"
    markdown_content += "|----|------|\n"

    markdown_content += f"| 功能序号 | {target_index} |\n"
    markdown_content += f"| 功能名称 | {func_name} |\n"
    markdown_content += f"| 简介 | {target_function.get('brief_des', '暂无简介') or '暂无简介'} |\n"

    trigger_method = target_function.get("trigger_method", "未知")
    trigger_condition = target_function.get("trigger_condition", "未知")
    markdown_content += f"| 触发方式 | {trigger_method} |\n"
    markdown_content += f"| 触发条件 | {trigger_condition} |\n"

    markdown_content += "\n"

    detail_des = target_function.get("detail_des", "")
    if detail_des:
        markdown_content += f"## 补充说明\n\n{detail_des}\n\n"

    markdown_content += "---\n\n"
    markdown_content += f"- **回到本插件功能列表**：「牛牛帮助 {plugin_name_display}」\n"
    markdown_content += "- **回到全部插件总列表**：「牛牛帮助」\n"

    return markdown_content, HelpMarkdownIssue.OK
