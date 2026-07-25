"""二级插件帮助页：C 顶栏/底栏 + 功能双列卡 + 底说明。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

    from .plugin_detail_data import PluginDetailData

from . import help_theme as ht
from .help_draw_assets import draw_page_footer_bar, draw_page_header_band, draw_page_meta_strip
from .help_draw_common import draw_body_block, measure_body_block_height, new_canvas, truncate_pixels
from .plugin_visuals import help_font, load_help_plugin_icon


def _layout_height(data: PluginDetailData) -> int:
    func_rows = max(1, math.ceil(len(data.functions) / ht.DETAIL_FUNC_COLS)) if data.functions else 0
    func_h = func_rows * ht.DETAIL_FUNC_CARD_H + max(0, func_rows - 1) * ht.DETAIL_FUNC_GAP
    chrome = ht.PAGE_HEADER_H + ht.PAGE_META_H + ht.PAGE_CHROME_GAP
    identity = ht.DETAIL_BANNER_ICON + 24
    body = 0
    if data.description:
        body += measure_body_block_height(data.description, width_chars=52)
    if data.usage:
        body += measure_body_block_height(data.usage, width_chars=52)
    for _title, content in data.extra_sections:
        body += measure_body_block_height(content, width_chars=52, title_size=22)
    footer = ht.PAGE_FOOTER_H + ht.PAGE_CHROME_GAP
    section = 32 if data.functions else 0
    return chrome + identity + section + func_h + body + footer + ht.DETAIL_PAD * 2


def draw_plugin_detail_image(data: PluginDetailData) -> Image.Image:
    height = _layout_height(data)
    hc = new_canvas(height, width=ht.DETAIL_WIDTH)
    draw, x1, y1, x2, y2 = hc.draw, hc.x1, hc.y1, hc.x2, hc.y2
    u = hc.u

    status_right = ""
    if data.enabled is not None:
        status_right = "已启用" if data.enabled else "已停用"
    cursor_y = draw_page_header_band(
        draw,
        x1=x1,
        y1=y1,
        x2=x2,
        title=data.display_name,
        right=status_right,
        scale=hc.scale,
    )
    if data.enabled is True:
        meta = f"关闭：牛牛关闭 {data.display_name}"
    elif data.enabled is False:
        meta = f"开启：牛牛开启 {data.display_name}"
    else:
        meta = f"牛牛帮助 {data.display_name} + 功能序号/名称"
    cursor_y = draw_page_meta_strip(draw, x1=x1, y=cursor_y, x2=x2, text=meta, scale=hc.scale)
    cursor_y += u(ht.PAGE_CHROME_GAP)

    icon_size = u(ht.DETAIL_BANNER_ICON)
    icon = load_help_plugin_icon(data.plugin, size=icon_size, label=data.display_name)
    hc.image.paste(icon, (x1 + u(24), cursor_y), icon)
    if data.enabled is not None:
        status_color = ht.STATUS_ON if data.enabled else ht.STATUS_OFF
        status_text = "开" if data.enabled else "关"
        chip_fill = ht.STATUS_ON_BG if data.enabled else ht.STATUS_OFF_BG
        chip_font = help_font(14)
        bbox = draw.textbbox((0, 0), status_text, font=chip_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bw, bh = tw + u(16), max(th + u(8), u(22))
        chip_x = x1 + u(24) + icon_size + u(16)
        chip_y = cursor_y + (icon_size - bh) // 2
        draw.rounded_rectangle((chip_x, chip_y, chip_x + bw, chip_y + bh), radius=u(8), fill=chip_fill)
        draw.text((chip_x + bw / 2, chip_y + bh / 2), status_text, fill=status_color, font=chip_font, anchor="mm")
    cursor_y += icon_size + u(16)

    if data.functions:
        draw.text((x1 + u(24), cursor_y), "功能一览", fill=ht.TEXT_TITLE, font=help_font(22))
        cursor_y += u(32)
        grid_x = x1 + u(24)
        for i, row in enumerate(data.functions):
            col = i % ht.DETAIL_FUNC_COLS
            line = i // ht.DETAIL_FUNC_COLS
            card_x = grid_x + col * u(ht.DETAIL_FUNC_CARD_W + ht.DETAIL_FUNC_GAP)
            card_y = cursor_y + line * u(ht.DETAIL_FUNC_CARD_H + ht.DETAIL_FUNC_GAP)
            _draw_function_card(hc, card_x, card_y, row)
        func_lines = math.ceil(len(data.functions) / ht.DETAIL_FUNC_COLS)
        cursor_y += func_lines * u(ht.DETAIL_FUNC_CARD_H) + max(0, func_lines - 1) * u(ht.DETAIL_FUNC_GAP) + u(16)

    cursor_y = draw_body_block(
        draw,
        x=x1 + u(24),
        y=cursor_y,
        max_x=x2 - u(24),
        title="说明",
        body=data.description,
        width_chars=52,
        scale=hc.scale,
    )
    cursor_y = draw_body_block(
        draw,
        x=x1 + u(24),
        y=cursor_y,
        max_x=x2 - u(24),
        title="插件内用法",
        body=data.usage,
        width_chars=52,
        scale=hc.scale,
    )
    for title, body in data.extra_sections:
        cursor_y = draw_body_block(
            draw,
            x=x1 + u(24),
            y=cursor_y,
            max_x=x2 - u(24),
            title=title,
            body=body,
            width_chars=52,
            scale=hc.scale,
        )

    footer = "返回总览：牛牛帮助"
    if data.functions:
        first = data.functions[0]
        footer += f" · 详情：牛牛帮助 {data.display_name} 2 或 牛牛帮助 {data.display_name} {first.func}"
    draw_page_footer_bar(draw, x1=x1, y2=y2, x2=x2, text=footer, scale=hc.scale)

    return hc.finish()


def _draw_function_card(hc, x: int, y: int, row) -> None:
    draw = hc.draw
    u = hc.u
    w, h = u(ht.DETAIL_FUNC_CARD_W), u(ht.DETAIL_FUNC_CARD_H)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=u(12), fill=ht.CARD, outline=ht.BORDER, width=max(1, hc.scale))
    name_font = help_font(18)
    small_font = help_font(14)
    title = truncate_pixels(draw, f"{row.index}. {row.func}", name_font, w - u(24))
    draw.text((x + u(14), y + u(12)), title, fill=ht.TEXT, font=name_font)
    cmd_y = y + u(12) + u(22) + u(ht.DETAIL_FUNC_TITLE_CMD_GAP)
    say = truncate_pixels(draw, row.say, small_font, w - u(24))
    draw.text((x + u(14), cmd_y), say, fill=ht.TEXT, font=small_font)
    meta_y = cmd_y + u(22)
    meta = truncate_pixels(draw, f"{row.scene} · {row.perm}", small_font, w - u(24))
    draw.text((x + u(14), meta_y), meta, fill=ht.TEXT_MUTED, font=small_font)
    if row.cooldown and row.cooldown != "—":
        cd_line = truncate_pixels(draw, row.cooldown, small_font, w - u(24))
        draw.text((x + u(14), meta_y + u(20)), cd_line, fill=ht.TEXT_MUTED, font=small_font)
