from nonebot import get_loaded_plugins, get_plugin_config, logger

from .config import Config
from .plugin_manager import plugin_display_name
from .visibility import load_help_hidden_plugins

plugin_config = get_plugin_config(Config)


def generate_plugins_markdown(
    plugin_config: Config, detail: bool = False, show_ignored: bool = False, ignored_plugins: list | None = None
) -> str:
    """生成一级菜单"""
    plugins = get_loaded_plugins()

    if show_ignored:
        # 超级用户在私聊时显示所有插件
        filtered_plugins = [plugin for plugin in plugins if plugin.name]
    else:
        # 普通情况，过滤掉忽略的插件
        ignored_plugins = ignored_plugins or (plugin_config.ignored_plugins if plugin_config else [])
        hidden_plugins = set(load_help_hidden_plugins())
        filtered_plugins = [
            plugin
            for plugin in plugins
            if plugin.name and plugin.name not in ignored_plugins and plugin.name not in hidden_plugins
        ]

    # 构建Markdown内容
    title = "# 牛牛帮助" if not show_ignored else "# 牛牛帮助 - 超级用户"
    markdown_content = f"{title}\n\n"
    markdown_content += f"总计加载插件数量: {len(filtered_plugins)}\n\n"

    markdown_content += "| 序号 | 插件名称 | 状态 | 插件简介 |\n"
    markdown_content += "|------|----------|------|----------|\n"

    sorted_plugins = sorted(filtered_plugins, key=lambda p: plugin_display_name(p))

    for index, plugin in enumerate(sorted_plugins, 1):
        plugin_name = plugin_display_name(plugin)

        # 添加插件简介
        if plugin.metadata:
            metadata = plugin.metadata
            description = metadata.description or "暂无描述"
        else:
            description = "暂无描述"

        # 状态占位符
        status_placeholder = "{status}"

        markdown_content += f"| {index} | {plugin_name} | {status_placeholder} | {description} |\n"

    if show_ignored:
        markdown_content += "\n> 超管视图：显示所有插件\n"

    markdown_content += "\n使用方法：\n"
    markdown_content += "- 发送 `牛牛帮助 <序号或插件名>` 查看某插件的详细说明\n"
    markdown_content += "- 发送 `牛牛开启 <序号或插件名>` 启用插件\n"
    markdown_content += "- 发送 `牛牛关闭 <序号或插件名>` 禁用插件\n"
    markdown_content += "\n示例：`牛牛帮助 1`、`牛牛帮助 帮助系统`。插件名也可使用与包名一致的英文标识。\n"
    return markdown_content


def generate_plugin_functions_markdown(
    plugin_config: Config, plugin_name: str, plugin_status: str | None = None
) -> str:
    """生成二级菜单"""
    plugins = get_loaded_plugins()

    target_plugin = None
    for plugin in plugins:
        if plugin.name and plugin.name.lower() == plugin_name.lower():
            target_plugin = plugin
            break

    if not target_plugin:
        for plugin in plugins:
            if plugin_display_name(plugin).lower() == plugin_name.lower():
                target_plugin = plugin
                break

    if not target_plugin:
        for plugin in plugins:
            if plugin.name and plugin_name.lower() in plugin.name.lower():
                target_plugin = plugin
                break

    if not target_plugin:
        for plugin in plugins:
            if plugin.name and plugin_name.lower() in plugin_display_name(plugin).lower():
                target_plugin = plugin
                break

    if not target_plugin:
        return f"# 未找到插件\n\n未找到名为 '{plugin_name}' 的插件。\n\n使用 `牛牛帮助` 查看所有插件。"

    plugin_name_display = plugin_display_name(target_plugin)
    markdown_content = f"# {plugin_name_display}"

    if plugin_status:
        status_display = "✅ 已启用" if plugin_status == "✅ 启用" else "⛔ 已禁用"
        markdown_content += f" ({status_display})\n\n"

        action_hint = "关闭" if plugin_status == "✅ 启用" else "开启"
        markdown_content += f"使用 `牛牛{action_hint} {plugin_name_display}` 可以{action_hint}此插件\n\n"
    else:
        markdown_content += " \n\n"

    if target_plugin.metadata:
        metadata = target_plugin.metadata
        description = metadata.description or "暂无描述"
        usage = metadata.usage or "暂无说明"
        markdown_content += f"**描述**: {description}\n\n"
        markdown_content += f"**使用方法**: {usage}\n\n"

        # 添加功能列表
        if hasattr(metadata, "extra") and metadata.extra:
            menu_data = metadata.extra.get("menu_data", [])
            if menu_data:
                markdown_content += "## 功能列表\n\n"
                markdown_content += "| 序号 | 功能名称 | 简要描述 |\n"
                markdown_content += "|------|----------|----------|\n"
                for i, item in enumerate(menu_data, 1):
                    func_name = item.get("func", f"未命名功能 {i}")
                    brief_des = item.get("brief_des", "暂无简介")
                    markdown_content += f"| {i} | {func_name} | {brief_des} |\n"
                markdown_content += (
                    "\n使用方法：发送 `牛牛帮助 <插件名> <功能序号或名称>` 查看本条功能的详情。"
                    "插件名可为中文展示名、序号或与包名一致的英文标识。\n\n"
                )
                markdown_content += "\n示例：`牛牛帮助 1 2`、`牛牛帮助 牛牛复读 1`\n\n"
            else:
                markdown_content += "该插件未定义功能列表。\n\n"
        else:
            markdown_content += "该插件未定义功能列表。\n\n"
    else:
        markdown_content += "该插件未定义元数据。\n\n"

    markdown_content += "---\n\n返回上一级：发送 `牛牛帮助` 回到插件列表\n"
    return markdown_content


def generate_function_detail_markdown(plugin_config: Config, plugin_name: str, function_name: str) -> str:
    """生成三级菜单"""
    plugins = get_loaded_plugins()

    target_plugin = None
    for plugin in plugins:
        if plugin.name and plugin.name.lower() == plugin_name.lower():
            target_plugin = plugin
            break

    if not target_plugin:
        for plugin in plugins:
            if plugin_display_name(plugin).lower() == plugin_name.lower():
                target_plugin = plugin
                break

    if not target_plugin:
        for plugin in plugins:
            if plugin.name and plugin_name.lower() in plugin.name.lower():
                target_plugin = plugin
                break

    if not target_plugin:
        for plugin in plugins:
            if plugin.name and plugin_name.lower() in plugin_display_name(plugin).lower():
                target_plugin = plugin
                break

    if not target_plugin:
        return f"# 未找到插件\n\n未找到名为 '{plugin_name}' 的插件。\n\n使用 `牛牛帮助` 查看所有插件。"

    if not target_plugin.metadata or not hasattr(target_plugin.metadata, "extra"):
        return f"# 错误\n\n插件 '{plugin_display_name(target_plugin)}' 未定义元数据。"

    metadata = target_plugin.metadata
    menu_data = metadata.extra.get("menu_data", []) if metadata.extra else []

    target_function = None
    target_index = -1

    # 如果function_name是数字，则将其作为序号处理
    if function_name.isdigit():
        index = int(function_name) - 1
        if 0 <= index < len(menu_data):
            target_function = menu_data[index]
            target_index = index + 1
    else:
        # 否则按名称匹配处理
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
        return f"# 未找到功能\n\n在插件 '{pd}' 中未找到功能 '{function_name}'。\n\n使用 `牛牛帮助 {pd}` 查看功能列表。"

    func_name = target_function.get("func", "未命名功能")
    plugin_name_display = plugin_display_name(target_plugin)
    markdown_content = f"# {plugin_name_display} - {func_name} 功能详情\n\n"

    markdown_content += "| 属性 | 详情 |\n"
    markdown_content += "|------|------|\n"

    markdown_content += f"| 功能序号 | {target_index} |\n"
    markdown_content += f"| 功能名称 | {func_name} |\n"
    markdown_content += f"| 简要描述 | {target_function.get('brief_des', '暂无简介') or '暂无简介'} |\n"

    trigger_method = target_function.get("trigger_method", "未知")
    trigger_condition = target_function.get("trigger_condition", "未知")
    markdown_content += f"| 触发方式 | {trigger_method} |\n"
    markdown_content += f"| 触发条件 | {trigger_condition} |\n"

    markdown_content += "\n"

    detail_des = target_function.get("detail_des", "")
    if detail_des:
        markdown_content += f"## 详细描述\n\n{detail_des}\n\n"

    markdown_content += "---\n\n"
    markdown_content += f"返回功能列表：`牛牛帮助 {plugin_name_display}`\n\n"
    markdown_content += "返回插件列表：`牛牛帮助`\n"

    return markdown_content


def generate_plugins_status_markdown(
    plugin_config: Config, scope_info: str = "当前群", show_ignored: bool = False, ignored_plugins: list | None = None
) -> str:
    """生成插件状态"""
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

    sorted_plugins = sorted(filtered_plugins, key=lambda p: plugin_display_name(p))
    logger.debug(f"生成插件状态Markdown: 共{len(sorted_plugins)}个插件")

    title = f"# 牛牛插件状态 ({scope_info})" if not show_ignored else f"# 牛牛插件状态 ({scope_info} - 超级用户)"
    markdown_content = f"{title}\n\n"
    markdown_content += f"总计加载插件数量: {len(sorted_plugins)}\n\n"

    markdown_content += "| 序号 | 插件名称 | 状态 | 插件简介 |\n"
    markdown_content += "|------|----------|------|----------|\n"

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
        markdown_content += "\n> 超管视图：显示所有插件\n"

    markdown_content += "\n使用方法：\n"
    markdown_content += "- 发送 `牛牛开启 <序号或插件名>` 启用插件\n"
    markdown_content += "- 发送 `牛牛关闭 <序号或插件名>` 禁用插件\n"
    markdown_content += "- 发送 `牛牛开启全部功能` 启用全部插件\n"
    markdown_content += "- 发送 `牛牛关闭全部功能` 禁用全部插件\n"

    markdown_content += "\n**说明：**仅群管理员与超级用户可更改插件开关状态\n"
    return markdown_content
