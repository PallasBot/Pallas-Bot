import re
import textwrap
from enum import StrEnum

from pallas.core.perm import (
    effective_permission_avail_text,
    help_say_phrase,
    help_scene_text,
    iter_plugin_detail_menu,
)

from .config import Config
from .help_constants import HELP_STATUS_OFF, HELP_STATUS_ON, HELP_STATUS_PLACEHOLDER
from .plugin_manager import find_plugin, get_help_menu_plugins, plugin_display_name
from .plugin_match import normalize_help_key

# 成图宽度与 pillowmd 默认版心大致对齐；总表「简介」列更窄
_HELP_DETAIL_WRAP = 44
_HELP_LIST_INTRO_WRAP = 22


def help_list_status_mark(enabled: bool) -> str:
    """一级列表表格「状态」列。"""
    return HELP_STATUS_ON if enabled else HELP_STATUS_OFF


def _plugin_page_status_banner(plugin_name_display: str, enabled: bool) -> str:
    """二级页标题下状态与开关口令。"""
    if enabled:
        return f"> **状态** 已启用 · 发送 **牛牛关闭 {plugin_name_display}** 可停用本插件\n\n"
    return f"> **状态** 已停用 · 发送 **牛牛开启 {plugin_name_display}** 可启用本插件\n\n"


def _sanitize_pipe(cell: str) -> str:
    return (cell or "").replace("|", "｜")


def _markdown_table_cell_linebreaks(text: str, width: int) -> str:
    """一级菜单：折叠空白为单行"""
    t = (text or "").strip()
    if not t:
        return "暂无"
    single = re.sub(r"\s+", " ", t.replace("\n", " "))
    return _sanitize_pipe(single)


def _markdown_table_cell_truncate(text: str, width: int) -> str:
    """二/三级菜单：折叠空白为单行，超过 width 时截断并加省略号。"""
    t = (text or "").strip()
    if not t:
        return "暂无"
    single = re.sub(r"\s+", " ", t.replace("\n", " "))
    single = _sanitize_pipe(single)
    if len(single) > width:
        return single[: width - 1] + "…"
    return single


def _is_markdown_table_block(block: str) -> bool:
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    return all("|" in ln for ln in lines)


def _is_bullet_block(block: str) -> bool:
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    return all(ln.startswith(("·", "•", "- ", "* ")) for ln in lines)


_NUMBERED_LINE_RE = re.compile(r"^\d+\.\s+")


def _is_numbered_list_block(block: str) -> bool:
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    return all(_NUMBERED_LINE_RE.match(ln) for ln in lines)


def _format_numbered_list_block(block: str, width: int) -> str:
    """保留有序列表行结构；每条占一行，避免 textwrap 在中文中间硬折行。"""
    del width  # PIL 按像素 truncate；markdown 段内也不拆序号条
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    formatted: list[str] = []
    for ln in lines:
        m = re.match(r"^(\d+\.\s+)(.+)$", ln)
        if not m:
            formatted.append(ln)
            continue
        formatted.append(m.group(1) + m.group(2))
    return "\n".join(formatted)


def _wrap_paragraphs_for_help_page(text: str, width: int = _HELP_DETAIL_WRAP) -> str:
    """详情页「说明」「用法」等：按空行分段后对每段 soft-wrap；表格与条目列表保持原样。"""
    if not (text or "").strip():
        return text or ""
    chunks: list[str] = []
    for block in (text or "").split("\n\n"):
        b = block.strip()
        if not b:
            continue
        if _is_markdown_table_block(b) or _is_bullet_block(b):
            chunks.append(b)
            continue
        if _is_numbered_list_block(b):
            chunks.append(_format_numbered_list_block(b, width))
            continue
        line = re.sub(r"[ \t\r\f\v]+", " ", b.replace("\n", " ")).strip()
        if not line:
            continue
        chunks.append(
            textwrap.fill(
                line,
                width=max(12, width),
                break_long_words=True,
                break_on_hyphens=True,
            )
        )
    return "\n\n".join(chunks)


class HelpMarkdownIssue(StrEnum):
    """帮助 Markdown 生成结果。"""

    OK = "ok"
    PLUGIN_NOT_FOUND = "plugin_not_found"
    METADATA_MISSING = "metadata_missing"
    FUNCTION_NOT_FOUND = "function_not_found"


def generate_plugins_markdown(
    plugin_config: Config,
    show_ignored: bool = False,
    ignored_plugins: list | None = None,
    *,
    filtered_plugins: list | None = None,
) -> str:
    """生成一级菜单。"""
    if filtered_plugins is None:
        filtered_plugins = get_help_menu_plugins(
            show_ignored=show_ignored,
            ignored_plugins=(
                None if show_ignored else (ignored_plugins or (plugin_config.ignored_plugins if plugin_config else []))
            ),
        )

    n = len(filtered_plugins)
    title = "# 牛牛帮助" if not show_ignored else "# 牛牛帮助（超级用户）"
    markdown_content = f"{title}\n\n"

    intro = f"共 **{n}** 个插件。"
    markdown_content += f"{_wrap_paragraphs_for_help_page(intro)}\n\n"
    markdown_content += "> **导航** ① 本页总览 → ② **牛牛帮助** + 序号或插件名 → ③ 再加功能序号或名称\n\n"
    markdown_content += (
        "> **示例**\n"
        "> **牛牛帮助 1** — 第 1 个插件的功能表\n"
        "> **牛牛帮助 MAA远控** — 按展示名打开\n"
        "> **牛牛帮助 1 2** — 第 1 个插件第 2 条详情\n\n"
    )
    markdown_content += (
        "> **单个开关** **牛牛开启** / **牛牛关闭** + 插件名\n"
        "> **批量开关** **牛牛开启全部功能** / **牛牛关闭全部功能**\n\n"
    )
    if show_ignored:
        markdown_content += (
            "> **超管·启停范围**\n"
            "> **本群** 群内 **牛牛开启/关闭** + 插件名，仅作用当前群\n"
            "> **单牛全局** 私聊 **牛牛开启 MAA远控** / **牛牛关闭 MAA远控**；群内加 **global** 后缀\n"
            "> **指定群** 私聊 **牛牛开启 MAA远控 123456789** / **牛牛关闭 MAA远控 123456789**\n"
            "> **全实例禁用** 于 WebUI 插件页勾选，对所有牛牛与群生效\n"
            "> 为指定群开通时会自动写入群白名单，亦可于同页手动维护\n\n"
        )

    markdown_content += "## 插件列表\n\n"
    markdown_content += f"「状态」列：**{HELP_STATUS_ON}**、**{HELP_STATUS_OFF}**（本群/私聊）。\n\n"
    markdown_content += "| 序号 | 插件名称 | 状态 | 简介 |\n"
    markdown_content += "|------|----------|------|------|\n"

    for index, plugin in enumerate(filtered_plugins, 1):
        plugin_name = plugin_display_name(plugin)

        if plugin.metadata:
            metadata = plugin.metadata
            description = metadata.description or "暂无描述"
        else:
            description = "暂无描述"
        description = _markdown_table_cell_linebreaks(description, _HELP_LIST_INTRO_WRAP)

        markdown_content += f"| {index} | {plugin_name} | {HELP_STATUS_PLACEHOLDER} | {description} |\n"

    if show_ignored:
        markdown_content += "\n> 本视图包含通常不在普通帮助里显示的插件，仅超级用户在私聊下可见。\n"

    markdown_content += "\n> 任意层级发 **牛牛帮助** 可回到本页。\n"
    return markdown_content


def generate_plugin_functions_markdown(
    plugin_name: str, plugin_enabled: bool | None = None
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
    markdown_content = f"# {plugin_name_display}\n\n"

    if plugin_enabled is not None:
        markdown_content += _plugin_page_status_banner(plugin_name_display, plugin_enabled)

    if target_plugin.metadata:
        metadata = target_plugin.metadata
        description = _wrap_paragraphs_for_help_page(metadata.description or "暂无描述")
        usage = _wrap_paragraphs_for_help_page(metadata.usage or "暂无说明")

        user_menu: list[dict] = []
        if hasattr(metadata, "extra") and metadata.extra:
            menu_data = metadata.extra.get("menu_data", [])
            user_menu = list(iter_plugin_detail_menu(target_plugin, menu_data))

        if user_menu:
            first_func = _sanitize_pipe(str(user_menu[0].get("func", "1") or "1"))
            markdown_content += "## 功能一览\n\n"
            detail_hint = (
                f"需要某一条的完整口令与步骤时，发「牛牛帮助 {plugin_name_display}」+ **序号**"
                f"（如「牛牛帮助 {plugin_name_display} 2」），"
                f"或 + **功能名**（如「牛牛帮助 {plugin_name_display} {first_func}」）。"
            )
            markdown_content += f"{_wrap_paragraphs_for_help_page(detail_hint)}\n\n"
            markdown_content += "| # | 功能 | 怎么说 | 场景 | 何人可用 |\n"
            markdown_content += "|---|------|--------|------|----------|\n"
            say_wrap = 28 if target_plugin.name == "maa" else 24
            for i, item in enumerate(user_menu, 1):
                func_name = _sanitize_pipe(str(item.get("func", f"未命名功能 {i}") or ""))
                say_cell = _markdown_table_cell_truncate(help_say_phrase(item), say_wrap)
                scene_cell = _markdown_table_cell_truncate(help_scene_text(item), 6)
                perm_raw = effective_permission_avail_text(item)
                perm_cell = _markdown_table_cell_truncate(perm_raw, 12) if perm_raw else "—"
                markdown_content += f"| {i} | {func_name} | {say_cell} | {scene_cell} | {perm_cell} |\n"
            markdown_content += "\n"

        markdown_content += "## 说明\n\n"
        markdown_content += f"{description}\n\n"

        if target_plugin.name == "maa":
            from pallas.core.plugin_coord import maa as maa_coord

            maa_http = _wrap_paragraphs_for_help_page(maa_coord.format_maa_http_setup_help())
            markdown_content += "## MAA 对接地址\n\n"
            markdown_content += f"{maa_http}\n\n"

        markdown_content += "## 插件内用法\n\n"
        markdown_content += f"{usage}\n\n"

        if not user_menu and hasattr(metadata, "extra"):
            markdown_content += "本插件未登记功能列表，仅见上文说明。\n\n"
    else:
        markdown_content += "本插件没有可用的元数据说明。\n\n"

    markdown_content += "---\n\n> 返回总览：**牛牛帮助**\n"
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
    user_menu = list(iter_plugin_detail_menu(target_plugin, menu_data))

    target_function = None
    target_index = -1

    if function_name.isdigit():
        index = int(function_name) - 1
        if 0 <= index < len(user_menu):
            target_function = user_menu[index]
            target_index = index + 1
    else:
        for index, item in enumerate(user_menu):
            func = item.get("func", "")
            if normalize_help_key(func) == normalize_help_key(function_name):
                target_function = item
                target_index = index + 1
                break

        if not target_function:
            arg_key = normalize_help_key(function_name)
            for index, item in enumerate(user_menu):
                func = item.get("func", "")
                if arg_key and arg_key in normalize_help_key(func):
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
    nav_bits = [f"「牛牛帮助 {plugin_name_display}」列表"]
    if target_index > 1:
        nav_bits.append(f"「牛牛帮助 {plugin_name_display} {target_index - 1}」上一条")
    if target_index < len(user_menu):
        nav_bits.append(f"「牛牛帮助 {plugin_name_display} {target_index + 1}」下一条")
    nav_bits.append("「牛牛帮助」总览")
    markdown_content += f"> 功能详情 · 第 **{target_index}/{len(user_menu)}** 条 · {' · '.join(nav_bits)}\n\n"

    say_plain = help_say_phrase(target_function)
    scene_plain = help_scene_text(target_function)
    perm_avail = effective_permission_avail_text(target_function)
    brief_cell = target_function.get("brief_des", "暂无简介") or "暂无简介"

    markdown_content += "| 项 | 内容 |\n|----|------|\n"
    markdown_content += f"| 怎么说 | {_sanitize_pipe(say_plain)} |\n"
    markdown_content += f"| 场景 | {_sanitize_pipe(scene_plain)} |\n"
    markdown_content += f"| 何人可用 | {_sanitize_pipe(perm_avail or '—')} |\n"
    markdown_content += f"| 简介 | {_sanitize_pipe(str(brief_cell).strip())} |\n\n"

    detail_des = target_function.get("detail_des", "")
    if detail_des:
        markdown_content += f"## 怎么用\n\n{_wrap_paragraphs_for_help_page(str(detail_des))}\n\n"

    if target_plugin.name == "maa" and func_name in {"绑定设备", "绑定 MAA 设备", "MAA HTTP"}:
        from pallas.core.plugin_coord import maa as maa_coord

        maa_http = _wrap_paragraphs_for_help_page(maa_coord.format_maa_http_setup_help())
        markdown_content += f"## MAA 对接地址\n\n{maa_http}\n\n"

    return markdown_content, HelpMarkdownIssue.OK
