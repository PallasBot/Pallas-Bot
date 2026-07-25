"""三级功能详情页：C 顶栏/底栏 + 文档流。"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image, ImageDraw

    from .plugin_detail_data import FunctionDetailData

from . import help_theme as ht
from .help_draw_assets import draw_page_footer_bar, draw_page_header_band, draw_page_meta_strip
from .help_draw_common import new_canvas, strip_help_markdown, truncate_pixels
from .plugin_visuals import help_font


def _chip_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0]) + 20


def _layout_height(data: FunctionDetailData) -> int:
    body = ht.PAGE_HEADER_H + ht.PAGE_META_H + ht.PAGE_CHROME_GAP
    chips = 0
    for value in (data.scene, data.perm, data.cooldown):
        if value and value != "—":
            chips += 1
    if chips:
        body += 36
    body += 72 + 18
    if data.brief:
        body += 28
    if data.detail:
        content = strip_help_markdown((data.detail or "").strip() or "暂无")
        lines = [ln for ln in textwrap.fill(content, width=52).splitlines() if ln.strip()] or ["暂无"]
        body += 30 + 28 + len(lines) * 26 + 16
    for _title, content in data.extra_sections:
        text = strip_help_markdown((content or "").strip() or "暂无")
        lines = [ln for ln in textwrap.fill(text, width=52).splitlines() if ln.strip()] or ["暂无"]
        body += 30 + 28 + len(lines) * 26 + 16
    return body + ht.PAGE_FOOTER_H + ht.PAGE_CHROME_GAP + ht.DETAIL_PAD * 2


def draw_function_detail_image(data: FunctionDetailData) -> Image.Image:
    height = _layout_height(data)
    hc = new_canvas(height, width=ht.DETAIL_WIDTH)
    draw, x1, y1, x2, y2 = hc.draw, hc.x1, hc.y1, hc.x2, hc.y2
    u = hc.u

    content_left = x1 + u(28)
    content_right = x2 - u(28)

    cursor_y = draw_page_header_band(
        draw,
        x1=x1,
        y1=y1,
        x2=x2,
        title=data.func_name,
        right=f"{data.index}/{data.total}",
        scale=hc.scale,
    )
    cursor_y = draw_page_meta_strip(
        draw,
        x1=x1,
        y=cursor_y,
        x2=x2,
        text=f"{data.display_name} · 功能详情",
        scale=hc.scale,
    )
    cursor_y += u(ht.PAGE_CHROME_GAP)

    chip_font = help_font(13)
    chips: list[str] = []
    if data.scene and data.scene != "—":
        chips.append(data.scene)
    if data.perm and data.perm != "—":
        chips.append(data.perm)
    if data.cooldown and data.cooldown != "—":
        chips.append(data.cooldown)
    chip_x = content_left
    for chip in chips:
        bw = _chip_width(draw, chip, chip_font) + u(8)
        bh = u(24)
        draw.rounded_rectangle((chip_x, cursor_y, chip_x + bw, cursor_y + bh), radius=u(8), fill=ht.CHIP_BG)
        draw.text((chip_x + bw / 2, cursor_y + bh / 2), chip, fill=ht.CHIP_FG, font=chip_font, anchor="mm")
        chip_x += bw + u(8)
    if chips:
        cursor_y += u(36)

    say = strip_help_markdown(data.say or "—")
    cmd_font = help_font(18)
    label_font = help_font(12)
    cmd_box_h = u(72)
    dark = ht.help_visual_mode() == "dark"
    draw.rounded_rectangle(
        (content_left, cursor_y, content_right, cursor_y + cmd_box_h),
        radius=u(12),
        fill=ht.COMMAND_BG,
        outline=ht.ACCENT if dark else ht.BORDER,
        width=max(1, hc.scale),
    )
    if not dark:
        draw.rectangle(
            (content_left, cursor_y + u(10), content_left + u(3), cursor_y + cmd_box_h - u(10)),
            fill=ht.ACCENT,
        )
    draw.text((content_left + u(16), cursor_y + u(12)), "触发", fill=ht.TEXT_MUTED, font=label_font)
    fitted = truncate_pixels(draw, say, cmd_font, content_right - content_left - u(32))
    draw.text((content_left + u(16), cursor_y + u(34)), fitted, fill=ht.COMMAND_FG, font=cmd_font)
    cursor_y += cmd_box_h + u(18)

    if data.brief:
        brief_font = help_font(16)
        draw.text((content_left, cursor_y), strip_help_markdown(data.brief), fill=ht.TEXT, font=brief_font)
        cursor_y += u(28)

    if data.detail:
        cursor_y = _draw_doc_section(
            hc,
            x=content_left,
            y=cursor_y,
            max_x=content_right,
            title="怎么用",
            body=data.detail,
        )
    for title, body in data.extra_sections:
        cursor_y = _draw_doc_section(
            hc,
            x=content_left,
            y=cursor_y,
            max_x=content_right,
            title=title,
            body=body,
        )

    nav_bits = [f"牛牛帮助 {data.display_name}"]
    if data.index > 1:
        nav_bits.append(f"牛牛帮助 {data.display_name} {data.index - 1}")
    if data.index < data.total:
        nav_bits.append(f"牛牛帮助 {data.display_name} {data.index + 1}")
    nav_bits.append("牛牛帮助")
    draw_page_footer_bar(draw, x1=x1, y2=y2, x2=x2, text=" · ".join(nav_bits), scale=hc.scale)

    return hc.finish()


def _draw_doc_section(hc, *, x: int, y: int, max_x: int, title: str, body: str) -> int:
    draw = hc.draw
    u = hc.u
    draw.text((x, y), title, fill=ht.TEXT_TITLE, font=help_font(20))
    cursor = y + u(30)
    content = strip_help_markdown((body or "").strip() or "暂无")
    wrapped = textwrap.fill(content, width=52)
    lines = [ln for ln in wrapped.splitlines() if ln.strip()] or ["暂无"]
    line_h = u(26)
    box_pad = u(14)
    box_h = box_pad * 2 + len(lines) * line_h
    draw.rounded_rectangle(
        (x, cursor, max_x, cursor + box_h),
        radius=u(10),
        fill=ht.CARD,
        outline=ht.BORDER,
        width=max(1, hc.scale),
    )
    draw.rectangle((x, cursor + u(8), x + u(3), cursor + box_h - u(8)), fill=ht.ACCENT)
    body_font = help_font(15)
    text_x = x + u(16)
    ty = cursor + box_pad
    for line in lines:
        fitted = truncate_pixels(draw, line, body_font, max_x - text_x - u(12))
        draw.text((text_x, ty), fitted, fill=ht.TEXT, font=body_font)
        ty += line_h
    return cursor + box_h + u(16)
