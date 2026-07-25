"""生成帮助图 v4 预览到仓库 tmp/（浅色 + 深色）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import nonebot

nonebot.init()

from packages.help.draw_function_detail import draw_function_detail_image  # noqa: E402
from packages.help.draw_plugin_detail import draw_plugin_detail_image  # noqa: E402
from packages.help.draw_plugin_menu import draw_plugin_menu_image  # noqa: E402
from packages.help.help_theme import set_help_visual_mode  # noqa: E402
from packages.help.menu_rows import HelpMenuRow  # noqa: E402
from packages.help.plugin_detail_data import (  # noqa: E402
    FunctionDetailData,
    HelpFunctionRow,
    PluginDetailData,
)


def _plugin(name: str, *, help_tag: str = "other") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        module=SimpleNamespace(__file__=__file__),
        metadata=SimpleNamespace(extra={"help_tag": help_tag}, description=""),
    )


def build_sample_menu_rows() -> list[HelpMenuRow]:
    samples = [
        (1, "牛牛帮助", "查看功能说明并管理开关", True, "core"),
        (2, "核心", "账号与基础能力", True, "core"),
        (3, "聊天", "学习与回复群消息", True, "chat"),
        (4, "AI", "大模型对话与记忆", True, "ai"),
        (5, "轮盘", "趣味轮盘游戏", False, "fun"),
        (6, "喝酒", "让牛牛喝酒或醒酒", True, "fun"),
        (7, "唱歌", "点歌与播放", True, "fun"),
        (8, "抽卡", "娱乐抽卡", True, "fun"),
        (9, "管理", "群管辅助", True, "admin"),
        (10, "工具", "实用小工具集合", True, "tool"),
        (11, "未分类插件", "尚未打标签的插件", True, "other"),
        (12, "演示", "预览用占位", False, "other"),
    ]
    rows: list[HelpMenuRow] = []
    for index, display, desc, enabled, tag in samples:
        plugin = _plugin(display, help_tag=tag)
        rows.append(
            HelpMenuRow(
                index=index,
                plugin=plugin,
                display_name=display,
                description=desc,
                enabled=enabled,
                help_tag=tag,
            )
        )
    return rows


def build_sample_plugin_detail() -> PluginDetailData:
    plugin = _plugin("聊天", help_tag="chat")
    functions = [
        HelpFunctionRow(1, "学习", "牛牛学习 〈关键词〉 〈回复〉", "群聊", "群管", "—", "教牛牛一句话", ""),
        HelpFunctionRow(2, "忘记", "牛牛忘记 〈关键词〉", "群聊", "群管", "—", "忘掉某条学习", ""),
        HelpFunctionRow(3, "发言", "群内自然触发", "群聊", "所有人", "—", "参与群聊回复", ""),
        HelpFunctionRow(4, "配置", "WebUI 控制台", "维护", "维护者", "—", "调整聊天参数", ""),
    ]
    return PluginDetailData(
        plugin=plugin,
        display_name="聊天",
        description="学习群消息并参与回复。可在本群开关本插件。",
        usage="1. 牛牛学习 关键词 回复\n2. 牛牛忘记 关键词\n3. 在群内自然聊天观察效果",
        enabled=True,
        functions=functions,
    )


def build_sample_function_detail() -> FunctionDetailData:
    plugin = _plugin("聊天", help_tag="chat")
    return FunctionDetailData(
        plugin=plugin,
        display_name="聊天",
        func_name="学习",
        index=1,
        total=4,
        say="牛牛学习 〈关键词〉 〈回复〉",
        scene="群聊",
        perm="群管",
        cooldown="—",
        brief="教牛牛记住一句话，命中关键词后按学习内容回复。",
        detail=(
            "发送「牛牛学习 关键词 回复」即可登记。\n"
            "1. 关键词尽量简短明确\n"
            "2. 回复避免过长以免刷屏\n"
            "3. 需要删除时用「牛牛忘记」"
        ),
    )


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)

    for mode, suffix in (("light", ""), ("dark", "_dark")):
        set_help_visual_mode(mode)  # type: ignore[arg-type]
        menu = draw_plugin_menu_image(
            build_sample_menu_rows(),
            show_ignored=False,
            page=1,
            total_pages=1,
            total_plugin_count=12,
            total_enabled_count=10,
        )
        menu_path = out_dir / f"help_preview_menu{suffix}.png"
        menu.save(menu_path)

        plugin = draw_plugin_detail_image(build_sample_plugin_detail())
        plugin_path = out_dir / f"help_preview_plugin{suffix}.png"
        plugin.save(plugin_path)

        function = draw_function_detail_image(build_sample_function_detail())
        function_path = out_dir / f"help_preview_function{suffix}.png"
        function.save(function_path)

        print(menu_path)
        print(plugin_path)
        print(function_path)

    set_help_visual_mode("light")


if __name__ == "__main__":
    main()
