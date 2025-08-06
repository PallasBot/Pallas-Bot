from nonebot import get_loaded_plugins, get_plugin_config, logger

from .config import Config

plugin_config = get_plugin_config(Config)


def generate_plugins_markdown(plugin_config: Config, detail: bool = False) -> str:
    """生成一级菜单"""
    plugins = get_loaded_plugins()

    ignored_plugins = plugin_config.ignored_plugins if plugin_config else []
    filtered_plugins = [plugin for plugin in plugins if plugin.name and plugin.name not in ignored_plugins]

    # 构建Markdown内容
    markdown_content = "# 牛牛帮助\n\n"
    markdown_content += f"总计加载插件数量: {len(filtered_plugins)}\n\n"

    markdown_content += "| 序号 | 插件名称 | 状态 | 插件简介 |\n"
    markdown_content += "|------|----------|------|----------|\n"

    # 按名称排序插件
    sorted_plugins = sorted(filtered_plugins, key=lambda p: p.name or "")

    for index, plugin in enumerate(sorted_plugins, 1):
        # 添加插件标题
        plugin_name = plugin.name or "未命名插件"

        # 添加插件简介
        if plugin.metadata:
            metadata = plugin.metadata
            description = metadata.description or "暂无描述"
        else:
            description = "暂无描述"

        # 状态占位符
        status_placeholder = "{status}"

        markdown_content += f"| {index} | {plugin_name} | {status_placeholder} | {description} |\n"

    markdown_content += "\n使用方法:\n"
    markdown_content += "- 使用 `牛牛帮助 <序号或插件名>` 查看插件详细功能\n"
    markdown_content += "- 使用 `牛牛开启 <序号或插件名>` 启用插件\n"
    markdown_content += "- 使用 `牛牛关闭 <序号或插件名>` 禁用插件\n"
    markdown_content += "\n示例: 牛牛帮助 1 或 牛牛帮助 帮助系统\n"
    return markdown_content


def generate_plugin_functions_markdown(plugin_config: Config, plugin_name: str, plugin_status: str = None) -> str:
    """生成二级菜单"""
    plugins = get_loaded_plugins()

    target_plugin = None
    for plugin in plugins:
        if plugin.name and plugin.name.lower() == plugin_name.lower():
            target_plugin = plugin
            break

    if not target_plugin:
        # 模糊匹配
        for plugin in plugins:
            if plugin.name and plugin_name.lower() in plugin.name.lower():
                target_plugin = plugin
                break

    if not target_plugin:
        return f"# 未找到插件\n\n未找到名为 '{plugin_name}' 的插件。\n\n使用 `牛牛帮助` 查看所有插件。"

    plugin_name_display = target_plugin.name or "未命名插件"
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
                markdown_content += "\n使用方法: 使用 `牛牛帮助 <插件名> <功能序号或名称>` 查看功能详情\n\n"
            else:
                markdown_content += "该插件未定义功能列表。\n\n"
        else:
            markdown_content += "该插件未定义功能列表。\n\n"
    else:
        markdown_content += "该插件未定义元数据。\n\n"

    markdown_content += "---\n\n返回上级: 使用 `牛牛帮助` 命令回到插件列表\n"
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
            if plugin.name and plugin_name.lower() in plugin.name.lower():
                target_plugin = plugin
                break

    if not target_plugin:
        return f"# 未找到插件\n\n未找到名为 '{plugin_name}' 的插件。\n\n使用 `牛牛帮助` 查看所有插件。"

    if not target_plugin.metadata or not hasattr(target_plugin.metadata, "extra"):
        return f"# 错误\n\n插件 '{target_plugin.name}' 未定义元数据。"

    metadata = target_plugin.metadata
    menu_data = metadata.extra.get("menu_data", []) if metadata.extra else []

    target_function = None
    target_index = -1
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
        return f"# 未找到功能\n\n在插件 '{target_plugin.name}' 中未找到功能 '{function_name}'。\n\n使用 `牛牛帮助 {target_plugin.name}` 查看功能列表。"  # noqa: E501

    func_name = target_function.get("func", "未命名功能")
    plugin_name_display = target_plugin.name or "未命名插件"
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
    markdown_content += f"返回功能列表: `牛牛帮助 {plugin_name_display}`\n\n"
    markdown_content += "返回插件列表: `牛牛帮助`\n"

    return markdown_content


def generate_plugins_status_markdown(plugin_config: Config, scope_info: str = "当前群") -> str:
    """生成插件状态"""
    plugins = get_loaded_plugins()

    ignored_plugins = plugin_config.ignored_plugins if plugin_config else []
    filtered_plugins = [plugin for plugin in plugins if plugin.name and plugin.name not in ignored_plugins]

    sorted_plugins = sorted(filtered_plugins, key=lambda p: p.name or "")
    logger.debug(f"生成插件状态Markdown: 共{len(sorted_plugins)}个插件")

    markdown_content = f"# 牛牛插件状态 ({scope_info})\n\n"
    markdown_content += f"总计加载插件数量: {len(sorted_plugins)}\n\n"

    markdown_content += "| 序号 | 插件名称 | 状态 | 插件简介 |\n"
    markdown_content += "|------|----------|------|----------|\n"

    for index, plugin in enumerate(sorted_plugins, 1):
        plugin_name = plugin.name or "未命名插件"

        if plugin.metadata:
            metadata = plugin.metadata
            description = metadata.description or "暂无描述"
        else:
            description = "暂无描述"

        status_placeholder = "{status}"

        markdown_content += f"| {index} | {plugin_name} | {status_placeholder} | {description} |\n"

    markdown_content += "\n使用方法:\n"
    markdown_content += "- 使用 `牛牛开启 <序号或插件名>` 启用插件\n"
    markdown_content += "- 使用 `牛牛关闭 <序号或插件名>` 禁用插件\n"
    markdown_content += "- 使用 `牛牛开启全部` 启用所有插件\n"
    markdown_content += "- 使用 `牛牛关闭全部` 禁用所有插件\n"

    markdown_content += "\n**注意:** 群管理员和超级用户才可操作插件状态\n"
    return markdown_content
