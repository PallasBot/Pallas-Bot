from types import SimpleNamespace

from packages.help.draw_function_detail import draw_function_detail_image
from packages.help.draw_plugin_detail import draw_plugin_detail_image
from packages.help.plugin_detail_data import FunctionDetailData, HelpFunctionRow, PluginDetailData


def test_draw_plugin_detail_image() -> None:
    plugin = SimpleNamespace(name="help", module=SimpleNamespace(__file__=__file__), metadata=None)
    data = PluginDetailData(
        plugin=plugin,
        display_name="牛牛帮助",
        description="查看功能说明，并管理本群常用插件开关。",
        usage="1. 牛牛帮助 — 总览\n2. 牛牛帮助 1 — 单插件",
        enabled=True,
        functions=[
            HelpFunctionRow(
                index=1,
                func="查看帮助",
                say="牛牛帮助",
                scene="群内/私聊",
                perm="所有人",
                cooldown="冷却 3 秒",
                brief="总览",
                detail="",
            )
        ],
    )
    image = draw_plugin_detail_image(data)
    assert image.width == 920
    assert image.height > 400


def test_draw_function_detail_image() -> None:
    plugin = SimpleNamespace(name="help", module=SimpleNamespace(__file__=__file__), metadata=None)
    data = FunctionDetailData(
        plugin=plugin,
        display_name="牛牛帮助",
        func_name="查看帮助",
        index=1,
        total=2,
        say="牛牛帮助",
        scene="群内/私聊",
        perm="所有人",
        cooldown="冷却 3 秒",
        brief="打开总览",
        detail="发送牛牛帮助即可查看插件总览。",
    )
    image = draw_function_detail_image(data)
    assert image.width == 920
    assert image.height > 300
