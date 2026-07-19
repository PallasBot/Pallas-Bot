"""三级功能详情页。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image, ImageDraw

    from .plugin_detail_data import FunctionDetailData

from .help_draw_common import draw_wrapped_block, new_canvas, truncate_pixels
from .help_theme import (
    BORDER,
    DETAIL_BANNER_H,
    DETAIL_BANNER_ICON,
    DETAIL_KV_CARD_H,
    DETAIL_KV_GAP,
    DETAIL_PAD,
    DETAIL_WIDTH,
    LINK,
    QUOTE_BG,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TEXT_TITLE,
)
from .plugin_visuals import help_font, load_help_plugin_icon


def _kv_half_width(content_left: int, content_right: int) -> int:
    inner = content_right - content_left
    return (inner - DETAIL_KV_GAP) // 2


def _layout_height(data: FunctionDetailData) -> int:
    grid_rows = 2
    body = grid_rows * (DETAIL_KV_CARD_H + DETAIL_KV_GAP) + DETAIL_KV_CARD_H + DETAIL_KV_GAP
    if data.detail:
        body += min(180, max(60, len(data.detail) // 2)) + 40
    body += len(data.extra_sections) * 100
    return DETAIL_BANNER_H + body + 80 + DETAIL_PAD * 2


def draw_function_detail_image(data: FunctionDetailData) -> Image.Image:
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
    draw.text((text_x, cursor_y + 18), data.display_name, fill=TEXT_MUTED, font=help_font(20))
    draw.text((text_x, cursor_y + 48), data.func_name, fill=TEXT_TITLE, font=help_font(32))
    draw.text((text_x, cursor_y + 92), f"第 {data.index}/{data.total} 条", fill=TEXT_MUTED, font=help_font(17))

    cursor_y = banner_bottom + 20
    content_left = x1 + 24
    content_right = x2 - 24
    half_w = _kv_half_width(content_left, content_right)
    grid_pairs = [
        [("怎么说", data.say), ("场景", data.scene)],
        [("何人可用", data.perm), ("冷却", data.cooldown)],
    ]
    for row in grid_pairs:
        for col, (label, value) in enumerate(row):
            card_x1 = content_left + col * (half_w + DETAIL_KV_GAP)
            card_x2 = card_x1 + half_w
            draw_kv_card(draw, card_x1, cursor_y, card_x2, label, value)
        cursor_y += DETAIL_KV_CARD_H + DETAIL_KV_GAP
    cursor_y = draw_kv_card(draw, content_left, cursor_y, content_right, "简介", data.brief)

    if data.detail:
        cursor_y = draw_wrapped_block(
            draw,
            x=x1 + 24,
            y=cursor_y + 8,
            max_x=x2 - 24,
            title="怎么用",
            body=data.detail,
            width_chars=46,
        )
    for title, body in data.extra_sections:
        cursor_y = draw_wrapped_block(
            draw, x=x1 + 24, y=cursor_y, max_x=x2 - 24, title=title, body=body, width_chars=46
        )

    nav_bits = [f"牛牛帮助 {data.display_name}"]
    if data.index > 1:
        nav_bits.append(f"牛牛帮助 {data.display_name} {data.index - 1}")
    if data.index < data.total:
        nav_bits.append(f"牛牛帮助 {data.display_name} {data.index + 1}")
    nav_bits.append("牛牛帮助")
    footer_y = y2 - 42
    draw.text((x1 + 24, footer_y), " · ".join(nav_bits), fill=LINK, font=help_font(16))

    return canvas.convert("RGB")


def draw_kv_card(draw: ImageDraw.ImageDraw, x1: int, y: int, x2: int, label: str, value: str) -> int:
    card_h = DETAIL_KV_CARD_H
    draw.rounded_rectangle((x1, y, x2, y + card_h), radius=10, fill=SURFACE, outline=BORDER, width=1)
    label_font = help_font(16)
    value_font = help_font(18)
    draw.text((x1 + 12, y + 8), label, fill=TEXT_MUTED, font=label_font)
    fitted = truncate_pixels(draw, value, value_font, x2 - x1 - 24)
    draw.text((x1 + 12, y + 28), fitted, fill=TEXT, font=value_font)
    return y + card_h + 10
