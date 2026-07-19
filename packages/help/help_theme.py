"""帮助图 v3 视觉令牌（对齐 docs/plugins/help/VISUAL.md）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pillowmd import Setting

from pallas.core.foundation.paths import project_path

CANVAS = (250, 247, 243)
SURFACE = (255, 252, 249)
BORDER = (210, 202, 194)
TEXT = (42, 38, 48)
TEXT_TITLE = (184, 67, 90)
TEXT_MUTED = (110, 104, 118)
TABLE_HEADER = (237, 230, 224)
QUOTE_BG = (245, 241, 236)
LINK = (91, 106, 184)
STATUS_ON = (52, 140, 90)
STATUS_OFF = (160, 120, 110)

MENU_WIDTH = 920
MENU_PAD = 36
MENU_COLS = 3
MENU_CARD_W = 260
MENU_CARD_H = 128
MENU_CARD_GAP = 18
MENU_ICON_SIZE = 64
MENU_CARD_TEXT_PAD = 14
MENU_STATUS_DOT = 8
MENU_FRAME_RADIUS = 24
MENU_CARD_RADIUS = 16

MENU_PAGE_SIZE = 20

DETAIL_WIDTH = 920
DETAIL_PAD = 36
DETAIL_BANNER_H = 136
DETAIL_BANNER_ICON = 96
DETAIL_FUNC_COLS = 2
DETAIL_FUNC_CARD_W = 400
DETAIL_FUNC_CARD_H = 128
DETAIL_FUNC_GAP = 16
DETAIL_FUNC_TITLE_CMD_GAP = 10
DETAIL_KV_CARD_H = 54
DETAIL_KV_COLS = 2
DETAIL_KV_GAP = 16
DETAIL_FOOTER_PAD = 56
DETAIL_STATUS_DOT = 8

PILLOWMD_DEFAULT_FONT = Setting.FONT_PATH / "smSans.ttf"
BUNDLED_SOURCE_HAN_SERIF = project_path("resource/fonts/SourceHanSerifCN-Regular.otf")
_FC_SERIF_FAMILIES = ("Source Han Serif SC", "思源宋体", "Noto Serif CJK SC")


def resolve_help_font_path() -> Path:
    """v3 成图字体：环境变量 > 仓库内置思源宋体 > fontconfig > smSans。"""
    override = (os.environ.get("PALLAS_HELP_V3_FONT") or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
    if BUNDLED_SOURCE_HAN_SERIF.is_file():
        return BUNDLED_SOURCE_HAN_SERIF
    for family in _FC_SERIF_FAMILIES:
        try:
            proc = subprocess.run(
                ["fc-match", "-f", "%{file}", family],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        candidate = Path((proc.stdout or "").strip())
        if not candidate.is_file():
            continue
        name = candidate.name.lower()
        if any(token in name for token in ("sourcehan", "notoserif", "serif")):
            return candidate
    return PILLOWMD_DEFAULT_FONT


FONT_PATH = resolve_help_font_path()
