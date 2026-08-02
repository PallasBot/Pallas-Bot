"""三级功能详情页：C 顶栏/底栏 + 文档流。"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from .plugin_detail_data import FunctionDetailData

from . import help_theme as ht
from .help_draw_assets import draw_page_footer_bar, draw_page_header_band, draw_page_meta_strip
from .help_draw_common import new_canvas, strip_help_markdown, truncate_pixels, wrap_pixels
from .plugin_visuals import help_font

_DOC_BODY_WRAP = 52
_DOC_BODY_FONT_SIZE = 15
_DOC_LINE_H = 26
_DOC_BOX_PAD = 14
_DOC_TEXT_INSET = 16 + 12  # text_x 相对 content + 右侧留白


def _chip_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0]) + 20


def _measure_draw() -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


def wrap_doc_body_lines(content: str, *, width: int = _DOC_BODY_WRAP) -> list[str]:
    """按空行分段 soft-wrap；保留段结构，避免把「可用音色」等另起段糊回一段。"""
    lines: list[str] = []
    for block in (content or "").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        stripped = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if stripped and all(ln.startswith(("·", "•", "- ", "* ")) for ln in stripped):
            lines.extend(stripped)
            continue
        for ln in stripped:
            if ln.startswith(("·", "•", "- ", "* ")):
                lines.append(ln)
                continue
            wrapped = textwrap.wrap(
                ln,
                width=max(12, width),
                break_long_words=False,
                break_on_hyphens=False,
            )
            lines.extend(wrapped or [ln])
    return lines or ["暂无"]


def expand_doc_body_lines(
    content: str,
    *,
    draw: ImageDraw.ImageDraw | None = None,
    font=None,
    max_width: int | None = None,
    width: int = _DOC_BODY_WRAP,
) -> list[str]:
    """结构折行后再按像素折行，保证长条目（如可用音色）完整可见。"""
    structural = wrap_doc_body_lines(content, width=width)
    if draw is None or font is None or max_width is None:
        return structural
    out: list[str] = []
    for line in structural:
        wrapped = wrap_pixels(draw, line, font, max_width)
        out.extend(wrapped or [line])
    return out or ["暂无"]


def _doc_text_max_width(*, scale: int = 1) -> int:
    # 与 draw_function_detail_image 内容区一致：左右 pad 28 + 文本 inset
    logical = ht.DETAIL_WIDTH - ht.DETAIL_PAD * 2 - 28 * 2 - _DOC_TEXT_INSET
    return max(1, logical * scale)


def _layout_height(data: FunctionDetailData) -> int:
    measure = _measure_draw()
    body_font = help_font(_DOC_BODY_FONT_SIZE)
    # help_font / 画布同乘 RENDER_SCALE；用缩放后的 max_w 估行数，高度仍用逻辑像素
    max_w = _doc_text_max_width(scale=max(1, int(ht.RENDER_SCALE)))
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
        lines = expand_doc_body_lines(content, draw=measure, font=body_font, max_width=max_w)
        body += 30 + _DOC_BOX_PAD * 2 + len(lines) * _DOC_LINE_H + 16
    for _title, content in data.extra_sections:
        text = strip_help_markdown((content or "").strip() or "暂无")
        lines = expand_doc_body_lines(text, draw=measure, font=body_font, max_width=max_w)
        body += 30 + _DOC_BOX_PAD * 2 + len(lines) * _DOC_LINE_H + 16
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
    body_font = help_font(_DOC_BODY_FONT_SIZE)
    text_x = x + u(16)
    max_text_w = max_x - text_x - u(12)
    lines = expand_doc_body_lines(content, draw=draw, font=body_font, max_width=max_text_w)
    line_h = u(_DOC_LINE_H)
    box_pad = u(_DOC_BOX_PAD)
    box_h = box_pad * 2 + len(lines) * line_h
    draw.rounded_rectangle(
        (x, cursor, max_x, cursor + box_h),
        radius=u(10),
        fill=ht.CARD,
        outline=ht.BORDER,
        width=max(1, hc.scale),
    )
    draw.rectangle((x, cursor + u(8), x + u(3), cursor + box_h - u(8)), fill=ht.ACCENT)
    ty = cursor + box_pad
    for line in lines:
        draw.text((text_x, ty), line, fill=ht.TEXT, font=body_font)
        ty += line_h
    return cursor + box_h + u(16)
