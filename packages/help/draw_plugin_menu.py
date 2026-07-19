"""一级帮助总览：PIL 卡片网格。"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw  # noqa: TC002

if TYPE_CHECKING:
    from .menu_rows import HelpMenuRow

from .help_draw_common import new_canvas, truncate_pixels
from .help_theme import (
    BORDER,
    LINK,
    MENU_CARD_GAP,
    MENU_CARD_H,
    MENU_CARD_RADIUS,
    MENU_CARD_TEXT_PAD,
    MENU_CARD_W,
    MENU_COLS,
    MENU_ICON_SIZE,
    MENU_PAD,
    MENU_STATUS_DOT,
    QUOTE_BG,
    STATUS_OFF,
    STATUS_ON,
    SURFACE,
    TABLE_HEADER,
    TEXT,
    TEXT_MUTED,
    TEXT_TITLE,
)
from .plugin_visuals import help_font, load_help_plugin_icon


def _card_text_width() -> int:
    return MENU_CARD_W - MENU_CARD_TEXT_PAD * 2 - MENU_ICON_SIZE - 12


def _card_name_width() -> int:
    return _card_text_width() - 28


def _measure_nav_block(show_ignored: bool) -> int:
    lines = 5 if show_ignored else 4
    return 28 * lines + 24


def _layout_height(row_count: int, show_ignored: bool, *, total_pages: int) -> int:
    rows = max(1, (row_count + MENU_COLS - 1) // MENU_COLS)
    cards_h = rows * MENU_CARD_H + max(0, rows - 1) * MENU_CARD_GAP
    header = 150 + _measure_nav_block(show_ignored)
    footer = 96 if total_pages > 1 else 72
    return header + cards_h + footer + MENU_PAD * 2


def draw_plugin_menu_image(
    menu_rows: list[HelpMenuRow],
    *,
    show_ignored: bool = False,
    page: int = 1,
    total_pages: int = 1,
    total_plugin_count: int | None = None,
    total_enabled_count: int | None = None,
) -> Image.Image:
    height = _layout_height(len(menu_rows), show_ignored, total_pages=total_pages)
    canvas, draw, x1, y1, x2, y2 = new_canvas(height)

    cursor_y = y1 + 28
    title_font = help_font(42)
    body_font = help_font(22)
    small_font = help_font(18)
    title = "牛牛帮助" if not show_ignored else "牛牛帮助（超级用户）"
    draw.text((x1 + 28, cursor_y), title, fill=TEXT_TITLE, font=title_font)
    cursor_y += 54

    total_count = total_plugin_count if total_plugin_count is not None else len(menu_rows)
    enabled_count = (
        total_enabled_count if total_enabled_count is not None else sum(1 for row in menu_rows if row.enabled)
    )
    subtitle = f"共 {total_count} 个插件 · 已启用 {enabled_count} 个"
    if total_pages > 1:
        subtitle += f" · 第 {page}/{total_pages} 页"
    draw.text((x1 + 28, cursor_y), subtitle, fill=TEXT_MUTED, font=body_font)
    cursor_y += 36

    hints = [
        "导航：本页总览 → 牛牛帮助 + 序号或插件名 → 再加功能序号或名称",
        "示例：牛牛帮助 1 · 牛牛帮助 MAA远控 · 牛牛帮助 1 2",
        "开关：牛牛开启/关闭 + 插件名；批量：牛牛开启全部功能 / 牛牛关闭全部功能",
    ]
    if total_pages > 1:
        hints.append("翻页：牛牛帮助 2页 / p2 / 第2页（插件序号仍为全局序号）")
    if show_ignored:
        hints.append("超管：本群/单牛全局/指定群/全实例禁用 — 见帮助说明")
    for hint in hints:
        box_top = cursor_y
        wrapped = textwrap.fill(hint, width=46)
        line_h = 24
        box_h = max(line_h + 12, wrapped.count("\n") * line_h + line_h + 12)
        draw.rounded_rectangle((x1 + 24, box_top, x2 - 24, box_top + box_h), radius=10, fill=QUOTE_BG)
        draw.text((x1 + 36, box_top + 8), wrapped, fill=TEXT, font=small_font)
        cursor_y = box_top + box_h + 10

    cursor_y += 8
    grid_x = x1 + 24
    for i, row in enumerate(menu_rows):
        col = i % MENU_COLS
        line = i // MENU_COLS
        card_x = grid_x + col * (MENU_CARD_W + MENU_CARD_GAP)
        card_y = cursor_y + line * (MENU_CARD_H + MENU_CARD_GAP)
        _draw_plugin_card(canvas, draw, card_x, card_y, row)

    footer_y = y2 - (58 if total_pages > 1 else 48)
    draw.text(
        (x1 + 28, footer_y),
        "发 牛牛帮助 + 插件名 查看功能详情 · 任意层级发 牛牛帮助 回到本页",
        fill=LINK,
        font=small_font,
    )
    if total_pages > 1:
        next_page = page + 1 if page < total_pages else 1
        draw.text(
            (x1 + 28, footer_y + 24),
            f"第 {page}/{total_pages} 页 · 牛牛帮助 {next_page}页 看{'下一' if page < total_pages else '第一'}页",
            fill=TEXT_MUTED,
            font=small_font,
        )
    if show_ignored:
        draw.text(
            (x1 + 28, footer_y + (48 if total_pages > 1 else 26)),
            "本视图含通常隐藏的插件，仅超级用户私聊可见",
            fill=TEXT_MUTED,
            font=small_font,
        )

    return canvas.convert("RGB")


def _draw_plugin_card(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, row: HelpMenuRow) -> None:
    w, h = MENU_CARD_W, MENU_CARD_H
    draw.rounded_rectangle((x, y, x + w, y + h), radius=MENU_CARD_RADIUS, fill=SURFACE, outline=BORDER, width=1)

    icon = load_help_plugin_icon(row.plugin, size=MENU_ICON_SIZE, label=row.display_name)
    canvas.paste(icon, (x + MENU_CARD_TEXT_PAD, y + (h - MENU_ICON_SIZE) // 2), icon)

    text_x = x + MENU_CARD_TEXT_PAD + MENU_ICON_SIZE + 12
    name_font = help_font(22)
    intro_font = help_font(16)
    status_font = help_font(17)
    name = truncate_pixels(draw, row.display_name, name_font, _card_name_width())
    draw.text((text_x, y + 14), name, fill=TEXT, font=name_font)

    status_color = STATUS_ON if row.enabled else STATUS_OFF
    dot_y = y + 48
    dot_x = text_x
    draw.ellipse((dot_x, dot_y, dot_x + MENU_STATUS_DOT, dot_y + MENU_STATUS_DOT), fill=status_color)
    status_text = "已启用" if row.enabled else "已停用"
    draw.text((text_x + MENU_STATUS_DOT + 6, y + 44), status_text, fill=status_color, font=status_font)

    intro = truncate_pixels(draw, row.description, intro_font, _card_text_width())
    draw.text((text_x, y + 72), intro, fill=TEXT_MUTED, font=intro_font)

    badge_font = help_font(14)
    badge = str(row.index)
    bbox = draw.textbbox((0, 0), badge, font=badge_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x, pad_y = 8, 5
    bw = tw + pad_x * 2
    bh = max(th + pad_y * 2, 22)
    badge_x1 = x + w - bw - 10
    badge_y1 = y + 10
    draw.rounded_rectangle((badge_x1, badge_y1, badge_x1 + bw, badge_y1 + bh), radius=8, fill=TABLE_HEADER)
    # 思源宋体数字 bbox 略偏左，+1px 光学居中
    draw.text(
        (badge_x1 + bw / 2 + 1, badge_y1 + bh / 2),
        badge,
        fill=TEXT_MUTED,
        font=badge_font,
        anchor="mm",
    )
