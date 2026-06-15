"""生成 help 默认样式九宫格资源（resource/styles/default/imgs）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# 设计令牌：与 docs/plugins/help/VISUAL.md 一致
CANVAS = (250, 247, 243)
SURFACE = (255, 252, 249)
BORDER = (210, 202, 194)
ACCENT = (184, 67, 90)

CORNER = 48
BORDER_W = 6
IMGS = Path(__file__).resolve().parents[1] / "resource" / "styles" / "default" / "imgs"


def _rounded_rect(
    size: tuple[int, int],
    radius: int,
    fill: tuple[int, ...],
    outline: tuple[int, ...] | None = None,
    outline_w: int = 0,
) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1),
        radius=radius,
        fill=fill,
        outline=outline,
        width=outline_w,
    )
    return img


def corner_lu() -> Image.Image:
    img = Image.new("RGBA", (CORNER, CORNER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, CORNER - 1, CORNER - 1),
        radius=20,
        fill=SURFACE + (255,),
        outline=BORDER + (255,),
        width=BORDER_W,
    )
    draw.rectangle((CORNER // 2, CORNER // 2, CORNER, CORNER), fill=(0, 0, 0, 0))
    return img


def corner_ru() -> Image.Image:
    return corner_lu().transpose(Image.Transpose.FLIP_LEFT_RIGHT)


def corner_ld() -> Image.Image:
    return corner_lu().transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def corner_rd() -> Image.Image:
    return corner_lu().transpose(Image.Transpose.ROTATE_180)


def strip_h(w: int) -> Image.Image:
    img = Image.new("RGBA", (w, CORNER), SURFACE + (255,))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, w, BORDER_W), fill=BORDER + (255,))
    draw.rectangle((0, CORNER - BORDER_W, w, CORNER), fill=BORDER + (255,))
    return img


def strip_v(h: int) -> Image.Image:
    img = Image.new("RGBA", (CORNER, h), SURFACE + (255,))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, BORDER_W, h), fill=BORDER + (255,))
    draw.rectangle((CORNER - BORDER_W, 0, CORNER, h), fill=BORDER + (255,))
    return img


def middle_tile() -> Image.Image:
    return Image.new("RGB", (64, 64), SURFACE)


def canvas_bg() -> Image.Image:
    """mode:0 回退用整图底（暖色纸面 + 细描边卡片感）。"""
    size = 800
    img = Image.new("RGB", (size, size), CANVAS)
    draw = ImageDraw.Draw(img)
    margin = 32
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=24,
        fill=SURFACE,
        outline=BORDER,
        width=2,
    )
# 左上角品牌点缀
    draw.ellipse((margin + 16, margin + 16, margin + 28, margin + 28), fill=ACCENT)
    return img


def main() -> None:
    IMGS.mkdir(parents=True, exist_ok=True)
    w, h = 320, 240

    corner_lu().save(IMGS / "nine_lu.png")
    corner_ru().save(IMGS / "nine_ru.png")
    corner_ld().save(IMGS / "nine_ld.png")
    corner_rd().save(IMGS / "nine_rd.png")
    strip_h(w).save(IMGS / "nine_u.png")
    strip_h(w).save(IMGS / "nine_d.png")
    strip_v(h).save(IMGS / "nine_l.png")
    strip_v(h).save(IMGS / "nine_r.png")
    middle_tile().save(IMGS / "nine_m.png")
    canvas_bg().save(IMGS / "background.png")

    print(f"wrote help style assets to {IMGS}")


if __name__ == "__main__":
    main()
