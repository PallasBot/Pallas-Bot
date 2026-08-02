from types import SimpleNamespace

from PIL import Image, ImageDraw

from packages.help.draw_function_detail import (
    draw_function_detail_image,
    expand_doc_body_lines,
    wrap_doc_body_lines,
)
from packages.help.draw_plugin_detail import draw_plugin_detail_image
from packages.help.help_draw_common import wrap_pixels
from packages.help.plugin_detail_data import FunctionDetailData, HelpFunctionRow, PluginDetailData
from packages.help.plugin_visuals import help_font


def test_wrap_doc_body_lines_keeps_paragraph_breaks() -> None:
    lines = wrap_doc_body_lines("继续上次未完成的歌曲。\n\n可用音色：\n\n· 牛牛、帕拉斯\n· 兔兔")
    assert lines[0] == "继续上次未完成的歌曲。"
    assert "可用音色：" in lines
    assert "· 牛牛、帕拉斯" in lines
    assert "· 兔兔" in lines
    assert "pallas" not in "\n".join(lines)


def test_expand_doc_body_lines_pixel_wraps_long_bullets() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = help_font(15)
    long = "· " + "、".join(f"音色{i}" for i in range(40))
    lines = expand_doc_body_lines(
        f"说明。\n\n可用音色：\n\n{long}",
        draw=draw,
        font=font,
        max_width=200,
    )
    assert any(ln.startswith("· ") for ln in lines)
    assert sum(1 for ln in lines if "音色" in ln) >= 2
    for ln in lines:
        assert "…" not in ln
        assert draw.textlength(ln, font=font) <= 200 + 1


def test_wrap_pixels_keeps_full_text() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = help_font(15)
    text = "帕拉斯；牛牛；兔兔；阿米娅；祥子、小祥、saki"
    parts = wrap_pixels(draw, text, font, 120)
    assert "".join(parts) == text
    assert len(parts) >= 2


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
