from types import SimpleNamespace

from PIL import Image, ImageDraw

from packages.help.draw_plugin_menu import draw_plugin_menu_image
from packages.help.help_draw_common import truncate_pixels
from packages.help.menu_rows import HelpMenuRow, paginate_menu_rows
from packages.help.plugin_visuals import help_font


def test_truncate_pixels_fits_card_width() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (400, 80)))
    font = help_font(16)
    long_text = "让牛牛喝酒、醒酒，并影响它后续的聊天状态与行为表现"
    fitted = truncate_pixels(draw, long_text, font, 156)
    assert draw.textlength(fitted, font=font) <= 156
    assert fitted.endswith("…")


def test_paginate_menu_rows_page_size_20() -> None:
    rows = [
        HelpMenuRow(index=i, plugin=SimpleNamespace(name=f"p{i}"), display_name=f"P{i}", description="", enabled=True)
        for i in range(1, 26)
    ]
    page_rows, page, total_pages = paginate_menu_rows(rows, page=2)
    assert page == 2
    assert total_pages == 2
    assert len(page_rows) == 5
    assert page_rows[0].index == 21


def test_draw_plugin_menu_image_dimensions() -> None:
    plugin = SimpleNamespace(name="help", module=SimpleNamespace(__file__=__file__), metadata=None)
    rows = [
        HelpMenuRow(index=1, plugin=plugin, display_name="牛牛帮助", description="查看功能说明", enabled=True),
        HelpMenuRow(index=2, plugin=plugin, display_name="示例插件", description="一行简介", enabled=False),
    ]
    image = draw_plugin_menu_image(rows, show_ignored=False, page=1, total_pages=1, total_plugin_count=2)
    assert image.width == 920
    assert image.height > 300
    assert image.mode == "RGB"
