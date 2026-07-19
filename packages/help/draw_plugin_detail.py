"""二级插件帮助页：banner + 功能卡片。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image, ImageDraw

    from .plugin_detail_data import PluginDetailData

from .help_draw_common import draw_body_block, measure_body_block_height, new_canvas, truncate_pixels
from .help_theme import (
    BORDER,
    DETAIL_BANNER_H,
    DETAIL_BANNER_ICON,
    DETAIL_FOOTER_PAD,
    DETAIL_FUNC_CARD_H,
    DETAIL_FUNC_CARD_W,
    DETAIL_FUNC_COLS,
    DETAIL_FUNC_GAP,
    DETAIL_FUNC_TITLE_CMD_GAP,
    DETAIL_PAD,
    DETAIL_STATUS_DOT,
    DETAIL_WIDTH,
    LINK,
    QUOTE_BG,
    STATUS_OFF,
    STATUS_ON,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TEXT_TITLE,
)
from .plugin_visuals import help_font, load_help_plugin_icon


def _layout_height(data: PluginDetailData) -> int:
    func_rows = max(1, math.ceil(len(data.functions) / DETAIL_FUNC_COLS)) if data.functions else 0
    func_h = func_rows * DETAIL_FUNC_CARD_H + max(0, func_rows - 1) * DETAIL_FUNC_GAP
    header = DETAIL_BANNER_H + 120
    body = 0
    if data.description:
        body += measure_body_block_height(data.description, width_chars=46)
    if data.usage:
        body += measure_body_block_height(data.usage, width_chars=46)
    for _title, content in data.extra_sections:
        body += measure_body_block_height(content, width_chars=46, title_size=24)
    footer = DETAIL_FOOTER_PAD + (48 if data.functions else 24)
    return header + func_h + body + footer + DETAIL_PAD * 2


def draw_plugin_detail_image(data: PluginDetailData) -> Image.Image:
    height = _layout_height(data)
    canvas, draw, x1, y1, x2, y2 = new_canvas(height, width=DETAIL_WIDTH)

    cursor_y = y1 + 20
    banner_bottom = cursor_y + DETAIL_BANNER_H
    banner_box = (x1 + 16, cursor_y, x2 - 16, banner_bottom)
    draw.rounded_rectangle(banner_box, radius=16, fill=QUOTE_BG, outline=BORDER, width=1)

    icon = load_help_plugin_icon(data.plugin, size=DETAIL_BANNER_ICON, label=data.display_name)
    icon_y = cursor_y + (DETAIL_BANNER_H - DETAIL_BANNER_ICON) // 2
    canvas.paste(icon, (x1 + 28, icon_y), icon)

    text_x = x1 + 28 + DETAIL_BANNER_ICON + 16
    title_font = help_font(34)
    draw.text((text_x, cursor_y + 22), data.display_name, fill=TEXT_TITLE, font=title_font)

    if data.enabled is not None:
        status_color = STATUS_ON if data.enabled else STATUS_OFF
        dot_y = cursor_y + 78
        draw.ellipse((text_x, dot_y, text_x + DETAIL_STATUS_DOT, dot_y + DETAIL_STATUS_DOT), fill=status_color)
        status_text = "已启用" if data.enabled else "已停用"
        draw.text((text_x + DETAIL_STATUS_DOT + 6, cursor_y + 72), status_text, fill=status_color, font=help_font(18))
        if data.enabled:
            hint = f"关闭：牛牛关闭 {data.display_name}"
        else:
            hint = f"开启：牛牛开启 {data.display_name}"
        draw.text((text_x, cursor_y + 98), hint, fill=TEXT_MUTED, font=help_font(16))

    cursor_y = banner_bottom + 16
    if data.functions:
        draw.text((x1 + 24, cursor_y), "功能一览", fill=TEXT_TITLE, font=help_font(26))
        cursor_y += 36
        grid_x = x1 + 24
        for i, row in enumerate(data.functions):
            col = i % DETAIL_FUNC_COLS
            line = i // DETAIL_FUNC_COLS
            card_x = grid_x + col * (DETAIL_FUNC_CARD_W + DETAIL_FUNC_GAP)
            card_y = cursor_y + line * (DETAIL_FUNC_CARD_H + DETAIL_FUNC_GAP)
            _draw_function_card(canvas, draw, card_x, card_y, row)
        func_lines = math.ceil(len(data.functions) / DETAIL_FUNC_COLS)
        cursor_y += func_lines * DETAIL_FUNC_CARD_H + max(0, func_lines - 1) * DETAIL_FUNC_GAP + 12

    cursor_y = draw_body_block(
        draw, x=x1 + 24, y=cursor_y, max_x=x2 - 24, title="说明", body=data.description, width_chars=46
    )
    cursor_y = draw_body_block(
        draw, x=x1 + 24, y=cursor_y, max_x=x2 - 24, title="插件内用法", body=data.usage, width_chars=46
    )
    for title, body in data.extra_sections:
        cursor_y = draw_body_block(draw, x=x1 + 24, y=cursor_y, max_x=x2 - 24, title=title, body=body, width_chars=46)

    footer_font = help_font(16)
    nav_font = help_font(17)
    footer_lines: list[tuple[str, tuple[int, int, int], object]] = [
        ("返回总览：牛牛帮助", LINK, nav_font),
    ]
    if data.functions:
        first = data.functions[0]
        footer_lines.append((
            f"详情：牛牛帮助 {data.display_name} 2 或 牛牛帮助 {data.display_name} {first.func}",
            TEXT_MUTED,
            footer_font,
        ))
    line_gap = 24
    block_h = (len(footer_lines) - 1) * line_gap + 22
    footer_y = y2 - block_h - 8
    for i, (text, color, font) in enumerate(footer_lines):
        draw.text((x1 + 24, footer_y + i * line_gap), text, fill=color, font=font)

    return canvas.convert("RGB")


def _draw_function_card(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, row) -> None:
    w, h = DETAIL_FUNC_CARD_W, DETAIL_FUNC_CARD_H
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=SURFACE, outline=BORDER, width=1)
    name_font = help_font(20)
    small_font = help_font(16)
    title = truncate_pixels(draw, f"{row.index}. {row.func}", name_font, w - 24)
    draw.text((x + 12, y + 10), title, fill=TEXT, font=name_font)
    cmd_y = y + 10 + 22 + DETAIL_FUNC_TITLE_CMD_GAP
    say = truncate_pixels(draw, f"命令：{row.say}", small_font, w - 24)
    draw.text((x + 12, cmd_y), say, fill=TEXT, font=small_font)
    meta_y = cmd_y + 22
    meta = truncate_pixels(draw, f"{row.scene} · {row.perm}", small_font, w - 24)
    draw.text((x + 12, meta_y), meta, fill=TEXT_MUTED, font=small_font)
    if row.cooldown and row.cooldown != "—":
        cd_line = truncate_pixels(draw, row.cooldown, small_font, w - 24)
        draw.text((x + 12, meta_y + 22), cd_line, fill=TEXT_MUTED, font=small_font)
