"""帮助图：pillowmd 默认用左右各 1px 叠字模拟加粗，中文易糊；改为细描边。"""

from __future__ import annotations

from typing import Any

import pillowmd.CustomMarkdownRenderer as cmr_mod  # noqa: N813

_PATCHED = False

# 帮助图加粗描边宽度
HELP_BOLD_STROKE_WIDTH = 0.30


def apply_help_light_bold_patch(stroke_width: float = HELP_BOLD_STROKE_WIDTH) -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    def text(
        self,
        xy,
        text,
        fill=None,
        font=None,
        use_lock_color=True,
        use_blod_mode=True,
        use_delete_line_mode=True,
        use_under_line_mode=True,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if font is None:
            raise SyntaxError("font为必选项")

        use_font = font
        mv = font.font_y_correct[font.font_name]

        for char in text:
            if not use_font.CheckChar(char):
                use_font, mv = use_font.ChoiceFontAndGetCorrent(char)
                break

        mv = round(mv * use_font.size / 100) if mv else 0

        if self.text_lock_color is not None and use_lock_color:
            fill = self.text_lock_color

        pos = (xy[0], xy[1] - mv)
        bold = bool(self.text_blod_mode and use_blod_mode and stroke_width > 0)

        draw_kwargs = dict(kwargs)
        if bold:
            draw_kwargs.setdefault("stroke_width", stroke_width)
            draw_kwargs.setdefault("stroke_fill", fill)
        cmr_mod.ImageDraw.ImageDraw.text(self, pos, text, fill, use_font, *args, **draw_kwargs)

        if self.delete_line_mode or self.under_line_mode:
            xs, _ys = font.GetSize(text)

        if self.delete_line_mode and use_delete_line_mode:
            cmr_mod.ImageDraw.ImageDraw.line(
                self,
                (xy[0], xy[1] + int(font.size / 2), xy[0] + xs, xy[1] + int(font.size / 2)),
                fill,
                int(font.size / 10) + 1,
            )

        if self.under_line_mode and use_under_line_mode:
            cmr_mod.ImageDraw.ImageDraw.line(
                self,
                (xy[0], xy[1] + font.size + 2, xy[0] + xs, xy[1] + font.size + 2),
                fill,
                int(font.size / 10) + 1,
            )

    cmr_mod.ImageDrawPro.text = text  # type: ignore[method-assign]
