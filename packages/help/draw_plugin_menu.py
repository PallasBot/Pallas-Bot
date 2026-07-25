"""一级帮助总览：三列卡片 + C 顶栏/底栏 + B 分组浅底。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image  # noqa: TC002

if TYPE_CHECKING:
    from .menu_rows import HelpMenuRow

from . import help_theme as ht
from .help_draw_assets import (
    draw_page_footer_bar,
    draw_page_header_band,
    draw_page_meta_strip,
    draw_section_banner,
)
from .help_draw_common import HelpCanvas, new_canvas, truncate_pixels
from .help_tags import group_rows_by_help_tag, help_tag_label
from .plugin_visuals import help_font, load_help_plugin_icon


def _card_text_width(scale: int) -> int:
    return (ht.MENU_CARD_W - ht.MENU_CARD_TEXT_PAD * 2 - ht.MENU_ICON_SIZE - 10) * scale


def _group_inner_height(rows: list[HelpMenuRow]) -> int:
    bar = ht.MENU_SECTION_BAR_H + 10
    lines = max(1, (len(rows) + ht.MENU_COLS - 1) // ht.MENU_COLS)
    cards = lines * ht.MENU_CARD_H + max(0, lines - 1) * ht.MENU_CARD_GAP
    return bar + cards


def _group_cards_height(groups: list[tuple[str, list[HelpMenuRow]]]) -> int:
    total = 0
    pad = ht.MENU_SECTION_PANEL_PAD
    for i, (_tag, rows) in enumerate(groups):
        if not rows:
            continue
        if i > 0:
            total += ht.MENU_SECTION_GAP
        total += pad * 2 + _group_inner_height(rows)
    return total


def _layout_height(groups: list[tuple[str, list[HelpMenuRow]]], *, total_pages: int) -> int:
    chrome = ht.PAGE_HEADER_H + ht.PAGE_META_H + ht.PAGE_CHROME_GAP
    cards_h = _group_cards_height(groups) or ht.MENU_CARD_H
    footer = ht.PAGE_FOOTER_H + (20 if total_pages > 1 else 0) + ht.PAGE_CHROME_GAP
    return chrome + cards_h + footer + ht.MENU_PAD * 2


def draw_plugin_menu_image(
    menu_rows: list[HelpMenuRow],
    *,
    show_ignored: bool = False,
    page: int = 1,
    total_pages: int = 1,
    total_plugin_count: int | None = None,
    total_enabled_count: int | None = None,
) -> Image.Image:
    groups = group_rows_by_help_tag(menu_rows, tag_of=lambda r: r.help_tag)
    height = _layout_height(groups, total_pages=total_pages)
    hc = new_canvas(height)
    draw, x1, y1, x2, y2 = hc.draw, hc.x1, hc.y1, hc.x2, hc.y2
    u = hc.u

    title = "牛牛帮助" if not show_ignored else "牛牛帮助（超级用户）"
    total_count = total_plugin_count if total_plugin_count is not None else len(menu_rows)
    enabled_count = (
        total_enabled_count if total_enabled_count is not None else sum(1 for row in menu_rows if row.enabled)
    )
    right = f"共 {total_count} 个 · 启用 {enabled_count}"
    if total_pages > 1:
        right += f" · {page}/{total_pages} 页"

    cursor_y = draw_page_header_band(draw, x1=x1, y1=y1, x2=x2, title=title, right=right, scale=hc.scale)
    meta = "牛牛帮助 + 序号/插件名 → 功能；开关：牛牛开启/关闭 + 插件名"
    if total_pages > 1:
        meta += " · 翻页：牛牛帮助 2页"
    if show_ignored:
        meta += " · 超管视图"
    cursor_y = draw_page_meta_strip(draw, x1=x1, y=cursor_y, x2=x2, text=meta, scale=hc.scale)
    cursor_y += u(ht.PAGE_CHROME_GAP)

    panel_x1 = x1 + u(24)
    panel_x2 = x2 - u(24)
    panel_pad = u(ht.MENU_SECTION_PANEL_PAD)
    card_w = u(ht.MENU_CARD_W)
    gap = u(ht.MENU_CARD_GAP)

    for gi, (tag, rows) in enumerate(groups):
        if not rows:
            continue
        if gi > 0:
            cursor_y += u(ht.MENU_SECTION_GAP)

        inner_h = u(_group_inner_height(rows))
        panel_h = panel_pad * 2 + inner_h
        draw.rounded_rectangle(
            (panel_x1, cursor_y, panel_x2, cursor_y + panel_h),
            radius=u(14),
            fill=ht.SECTION_PANEL,
            outline=ht.BORDER,
            width=max(1, hc.scale),
        )
        inner_x = panel_x1 + panel_pad
        inner_y = cursor_y + panel_pad
        after_banner = draw_section_banner(
            hc.image,
            draw,
            x1=inner_x,
            x2=panel_x2 - panel_pad,
            y=inner_y,
            label=help_tag_label(tag),
            height=u(ht.MENU_SECTION_BAR_H),
            scale=hc.scale,
        )
        for i, row in enumerate(rows):
            col = i % ht.MENU_COLS
            line = i // ht.MENU_COLS
            card_x = inner_x + col * (card_w + gap)
            card_y = after_banner + line * u(ht.MENU_CARD_H + ht.MENU_CARD_GAP)
            _draw_plugin_card(hc, card_x, card_y, row)
        cursor_y += panel_h

    footer = "发 牛牛帮助 + 插件名 查看功能 · 任意层级发 牛牛帮助 回总览"
    if total_pages > 1:
        next_page = page + 1 if page < total_pages else 1
        footer = f"第 {page}/{total_pages} 页 · 牛牛帮助 {next_page}页 · {footer}"
    draw_page_footer_bar(draw, x1=x1, y2=y2, x2=x2, text=footer, scale=hc.scale)

    return hc.finish()


def _draw_plugin_card(hc: HelpCanvas, x: int, y: int, row: HelpMenuRow) -> None:
    draw = hc.draw
    u = hc.u
    w, h = u(ht.MENU_CARD_W), u(ht.MENU_CARD_H)
    draw.rounded_rectangle(
        (x, y, x + w, y + h),
        radius=u(ht.MENU_CARD_RADIUS),
        fill=ht.CARD,
        outline=ht.BORDER,
        width=max(1, hc.scale),
    )

    icon_size = u(ht.MENU_ICON_SIZE)
    icon = load_help_plugin_icon(row.plugin, size=icon_size, label=row.display_name)
    hc.image.paste(icon, (x + u(ht.MENU_CARD_TEXT_PAD), y + (h - icon_size) // 2), icon)

    text_x = x + u(ht.MENU_CARD_TEXT_PAD) + icon_size + u(10)
    name_font = help_font(20)
    intro_font = help_font(14)

    name = truncate_pixels(
        draw,
        f"{row.index}. {row.display_name}",
        name_font,
        _card_text_width(hc.scale) - u(40),
    )
    draw.text((text_x, y + u(24)), name, fill=ht.TEXT, font=name_font)

    status_color = ht.STATUS_ON if row.enabled else ht.STATUS_OFF
    status_text = "开" if row.enabled else "关"
    badge_font = help_font(14)
    bbox = draw.textbbox((0, 0), status_text, font=badge_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    bw, bh = tw + u(10), max(th + u(4), u(20))
    name_w = draw.textlength(name, font=name_font)
    badge_x1 = min(text_x + int(name_w) + u(6), x + w - bw - u(8))
    badge_y1 = y + u(24)
    chip_fill = ht.STATUS_ON_BG if row.enabled else ht.STATUS_OFF_BG
    draw.rounded_rectangle((badge_x1, badge_y1, badge_x1 + bw, badge_y1 + bh), radius=u(999), fill=chip_fill)
    draw.text(
        (badge_x1 + bw / 2, badge_y1 + bh / 2),
        status_text,
        fill=status_color,
        font=badge_font,
        anchor="mm",
    )

    intro = truncate_pixels(draw, row.description, intro_font, _card_text_width(hc.scale))
    draw.text((text_x, y + u(74)), intro, fill=ht.TEXT_MUTED, font=intro_font)
