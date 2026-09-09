"""HTML 帮助图专用视觉令牌。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

HtmlThemeMode = Literal["light", "dark"]
HTML_THEME_PATH = Path(__file__).resolve()

_FIXED: dict[str, str] = {
    "canvas": "#7A898B",
    "content_background": "#C9D2D1",
    "record_body": "#F1F3EF",
    "record_body_alt": "#E6ECE9",
    "record_header": "#26343A",
    "record_header_alt": "#35474E",
    "text": "#1D2A30",
    "text_muted": "#52676C",
    "text_on_dark": "#F1F4F1",
    "line": "#88989A",
    "cyan": "#3CC3E3",
    "chartreuse": "#E8D63A",
    "status_on": "#257A67",
    "status_off": "#A94D50",
}


def get_html_theme(_mode: HtmlThemeMode | None = None) -> dict[str, str]:
    """返回固定的档案灰阶，不修改 Pillow 主题。"""
    theme = dict(_FIXED)
    theme.update({
        "paper": theme["content_background"],
        "panel": theme["record_body_alt"],
        "card": theme["record_body"],
        "ink": theme["text"],
        "text_title": theme["text"],
        "muted": theme["text_muted"],
        "border": theme["line"],
        "accent": theme["cyan"],
        "amber": theme["chartreuse"],
        "header": theme["record_header"],
        "header_bg": theme["record_header"],
        "header_panel": theme["record_header_alt"],
        "header_fg": theme["text_on_dark"],
        "header_muted": "#B9C7C4",
        "section_panel": theme["record_body_alt"],
        "footer_bg": theme["record_header"],
        "command_bg": theme["record_header_alt"],
        "command_fg": theme["text_on_dark"],
        "status_on_bg": theme["record_body_alt"],
        "status_off_bg": "#ECD9D8",
        "success": theme["status_on"],
        "danger": theme["status_off"],
        "chip_bg": theme["record_body_alt"],
        "chip_fg": "#126B7F",
        "grid": "rgba(80, 86, 83, .05)",
    })
    return theme


def html_theme_revision() -> str:
    try:
        stat = HTML_THEME_PATH.stat()
        digest = hashlib.sha256(HTML_THEME_PATH.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}:{digest}"


__all__ = ["HTML_THEME_PATH", "HtmlThemeMode", "get_html_theme", "html_theme_revision"]
