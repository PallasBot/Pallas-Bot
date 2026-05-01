"""与 HTTP 控制台、日志环相关的通用能力。"""

from .bot_web import (
    install_nonebot_log_sink,
    nonebot_log_record_matches_http_facet,
    public_base_url,
    tail_nonebot_log_lines,
    tail_nonebot_log_lines_scoped,
)

__all__ = [
    "install_nonebot_log_sink",
    "nonebot_log_record_matches_http_facet",
    "public_base_url",
    "tail_nonebot_log_lines",
    "tail_nonebot_log_lines_scoped",
]
