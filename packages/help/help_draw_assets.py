"""帮助图轻量装饰：优先加载 assets，否则几何绘制。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from pallas.core.foundation.paths import project_path

from . import help_theme as ht
from .plugin_visuals import help_font

_ASSETS = Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=8)
def _optional_asset(name: str) -> Image.Image | None:
    path = _ASSETS / name
    if not path.is_file():
        alt = project_path("packages/help/assets") / name
        path = alt if alt.is_file() else path
    if not path.is_file():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        return None


def draw_section_banner(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    x2: int,
    y: int,
    label: str,
    height: int = 24,
    scale: int = 1,
) -> int:
    """分组标题：随文字宽度的短标签，不拉全宽色条。height 已是像素（可含 scale）。"""
    del x2
    font = help_font(15)
    text = label.strip() or "其他"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x, pad_y = 10 * scale, 5 * scale
    bw = tw + pad_x * 2
    bh = max(height, th + pad_y * 2)

    chip = _optional_asset("section_chip.png")
    if chip is not None and ht.help_visual_mode() == "light":
        scaled = chip.resize((bw, bh), Image.Resampling.LANCZOS)
        canvas.paste(scaled, (x1, y), scaled)
    else:
        draw.rounded_rectangle((x1, y, x1 + bw, y + bh), radius=8 * scale, fill=ht.CHIP_BG)
        if ht.help_visual_mode() == "dark":
            draw.rounded_rectangle((x1, y, x1 + 4 * scale, y + bh), radius=2 * scale, fill=ht.TITLE_GLOW)
    ox = 2 * scale if ht.help_visual_mode() == "dark" else 0
    draw.text((x1 + bw / 2 + ox, y + bh / 2), text, fill=ht.CHIP_FG, font=font, anchor="mm")
    return y + bh + 10 * scale


def draw_header_accent(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    y: int,
    width: int = 48,
    scale: int = 1,
) -> None:
    """标题下短强调线。width 已是像素。"""
    del scale
    draw.rounded_rectangle((x1, y, x1 + width, y + max(2, width // 12)), radius=2, fill=ht.ACCENT)


def draw_page_header_band(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    y1: int,
    x2: int,
    title: str,
    right: str = "",
    scale: int = 1,
) -> int:
    """C：满宽浅色顶栏 + 底边品牌紫细线。返回顶栏下沿 y。"""
    h = ht.PAGE_HEADER_H * scale
    draw.rectangle((x1, y1, x2, y1 + h), fill=ht.HEADER_BG)
    line_w = max(2, 2 * scale)
    draw.rectangle((x1, y1 + h - line_w, x2, y1 + h), fill=ht.ACCENT)
    title_font = help_font(28)
    draw.text((x1 + 24 * scale, y1 + h // 2), title, fill=ht.HEADER_FG, font=title_font, anchor="lm")
    if right:
        right_font = help_font(16)
        draw.text((x2 - 24 * scale, y1 + h // 2), right, fill=ht.HEADER_MUTED, font=right_font, anchor="rm")
    return y1 + h


def draw_page_meta_strip(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    y: int,
    x2: int,
    text: str,
    scale: int = 1,
) -> int:
    """顶栏下浅色元信息条。"""
    h = ht.PAGE_META_H * scale
    draw.rectangle((x1, y, x2, y + h), fill=ht.META_STRIP_BG)
    draw.line((x1, y + h - max(1, scale), x2, y + h - max(1, scale)), fill=ht.BORDER, width=max(1, scale))
    font = help_font(14)
    draw.text((x1 + 24 * scale, y + h // 2), text, fill=ht.TEXT_MUTED, font=font, anchor="lm")
    return y + h


def draw_page_footer_bar(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    y2: int,
    x2: int,
    text: str,
    scale: int = 1,
) -> int:
    """底栏导航条；返回条顶 y。"""
    h = ht.PAGE_FOOTER_H * scale
    top = y2 - h
    draw.rectangle((x1, top, x2, y2), fill=ht.FOOTER_BAR_BG)
    draw.line((x1, top, x2, top), fill=ht.BORDER, width=max(1, scale))
    font = help_font(14)
    draw.text((x1 + 24 * scale, top + h // 2), text, fill=ht.LINK, font=font, anchor="lm")
    return top
