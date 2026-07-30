"""帮助图 v4 视觉令牌：浅色控制台 / 深色面板。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from pillowmd import Setting

from pallas.core.foundation.paths import project_path

HelpVisualMode = Literal["light", "dark"]

# 布局常量（两套主题共用）
# 版心对齐现网 920；总览三列，卡片宽按版心均分
MENU_WIDTH = 920
MENU_PAD = 36
MENU_COLS = 3
MENU_CARD_W = 249
MENU_CARD_H = 128
MENU_CARD_GAP = 16
MENU_ICON_SIZE = 56
MENU_CARD_TEXT_PAD = 12
MENU_STATUS_DOT = 8
MENU_FRAME_RADIUS = 24
MENU_CARD_RADIUS = 16
MENU_SECTION_GAP = 10
MENU_SECTION_BAR_H = 28
MENU_SECTION_PANEL_PAD = 10
# C 方案：顶栏 / 元信息条 / 底栏（逻辑像素）
PAGE_HEADER_H = 58
PAGE_META_H = 34
PAGE_FOOTER_H = 40
PAGE_CHROME_GAP = 12

DETAIL_WIDTH = 920
DETAIL_PAD = 36
DETAIL_BANNER_H = 136
DETAIL_BANNER_ICON = 96
DETAIL_FUNC_COLS = 2
DETAIL_FUNC_CARD_W = 400
DETAIL_FUNC_CARD_H = 148
DETAIL_FUNC_GAP = 16
DETAIL_FUNC_TITLE_CMD_GAP = 8
DETAIL_FUNC_BRIEF_GAP = 6
DETAIL_KV_CARD_H = 54
DETAIL_KV_COLS = 2
DETAIL_KV_GAP = 16
DETAIL_FOOTER_PAD = 56
DETAIL_STATUS_DOT = 8

# 2× 绘制再 LANCZOS 缩回，圆角/文字更锐利
RENDER_SCALE = 2

_LIGHT = {
    # Docs/WebUI 品牌紫：#7c3aed / soft ≈ brand-soft
    "CANVAS": (247, 245, 252),
    "SURFACE": (255, 255, 255),
    "CARD": (255, 255, 255),
    "BORDER": (228, 224, 238),
    "TEXT": (28, 30, 36),
    "TEXT_TITLE": (28, 30, 36),
    "TEXT_MUTED": (136, 140, 150),
    "ACCENT": (124, 58, 237),
    "TABLE_HEADER": (244, 241, 250),
    "QUOTE_BG": (244, 241, 250),
    "CHIP_BG": (243, 237, 254),
    "CHIP_FG": (109, 40, 217),
    "LINK": (124, 58, 237),
    "STATUS_ON": (46, 125, 50),
    "STATUS_OFF": (198, 40, 40),
    "STATUS_ON_BG": (232, 245, 233),
    "STATUS_OFF_BG": (252, 228, 236),
    "COMMAND_BG": (244, 241, 250),
    "COMMAND_FG": (28, 30, 36),
    "SECTION_BAR": (124, 58, 237),
    "SECTION_PANEL": (246, 243, 252),
    "BANNER_BG": (244, 241, 250),
    "TITLE_GLOW": (124, 58, 237),
    # C：浅色顶栏（满宽信息带，避免大块深紫）
    "HEADER_BG": (244, 241, 250),
    "HEADER_FG": (28, 30, 36),
    "HEADER_MUTED": (110, 100, 140),
    "META_STRIP_BG": (255, 255, 255),
    "FOOTER_BAR_BG": (244, 241, 250),
}

# 深色面板（紫调对齐品牌）
_DARK = {
    "CANVAS": (14, 12, 28),
    "SURFACE": (26, 22, 48),
    "CARD": (36, 32, 68),
    "BORDER": (88, 72, 140),
    "TEXT": (230, 232, 242),
    "TEXT_TITLE": (255, 255, 255),
    "TEXT_MUTED": (156, 148, 190),
    "ACCENT": (167, 139, 250),
    "TABLE_HEADER": (42, 36, 76),
    "QUOTE_BG": (34, 28, 62),
    "CHIP_BG": (88, 56, 180),
    "CHIP_FG": (255, 255, 255),
    "LINK": (196, 181, 253),
    "STATUS_ON": (110, 220, 150),
    "STATUS_OFF": (255, 120, 140),
    "STATUS_ON_BG": (36, 72, 56),
    "STATUS_OFF_BG": (72, 36, 52),
    "COMMAND_BG": (18, 16, 36),
    "COMMAND_FG": (245, 245, 250),
    "SECTION_BAR": (167, 139, 250),
    "SECTION_PANEL": (32, 28, 58),
    "BANNER_BG": (40, 32, 78),
    "TITLE_GLOW": (167, 139, 250),
    "HEADER_BG": (40, 32, 78),
    "HEADER_FG": (255, 255, 255),
    "HEADER_MUTED": (196, 181, 253),
    "META_STRIP_BG": (26, 22, 48),
    "FOOTER_BAR_BG": (34, 28, 62),
}

_active: HelpVisualMode = "light"


def help_visual_mode() -> HelpVisualMode:
    return _active


def set_help_visual_mode(mode: HelpVisualMode) -> HelpVisualMode:
    """切换浅色 / 深色令牌；绘制侧请从本模块读属性，勿缓存局部绑定。"""
    global _active
    import sys

    palette = _DARK if mode == "dark" else _LIGHT
    _active = mode
    mod = sys.modules[__name__]
    for key, value in palette.items():
        setattr(mod, key, value)
    return _active


def resolve_help_visual_mode_from_env() -> HelpVisualMode:
    raw = (os.environ.get("PALLAS_HELP_VISUAL") or "").strip().lower()
    if raw in ("dark", "light"):
        return raw  # type: ignore[return-value]
    return "light"


# 启动默认：环境变量，否则浅色（深色预览由脚本显式切换）
set_help_visual_mode(resolve_help_visual_mode_from_env())

PILLOWMD_DEFAULT_FONT = Setting.FONT_PATH / "smSans.ttf"
BUNDLED_SOURCE_HAN_SERIF = project_path("resource/fonts/SourceHanSerifCN-Regular.otf")
_FC_SANS_FAMILIES = ("Source Han Sans SC", "思源黑体", "Noto Sans CJK SC", "WenQuanYi Micro Hei")
_FC_SERIF_FAMILIES = ("Source Han Serif SC", "思源宋体", "Noto Serif CJK SC")


def resolve_help_font_path() -> Path:
    """成图字体：环境变量 > smSans 无衬线 > 系统黑体 > 思源宋体。"""
    override = (os.environ.get("PALLAS_HELP_V3_FONT") or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
    # UI 面板锐利度：优先无衬线，宋体放最后
    if PILLOWMD_DEFAULT_FONT.is_file():
        return PILLOWMD_DEFAULT_FONT
    for family in _FC_SANS_FAMILIES:
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
        if candidate.is_file():
            return candidate
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
