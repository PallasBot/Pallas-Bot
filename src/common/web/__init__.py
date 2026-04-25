"""与 HTTP 控制台、日志环相关的通用能力。"""

from .bot_web import install_nonebot_log_sink, public_base_url, tail_nonebot_log_lines

__all__ = ["install_nonebot_log_sink", "public_base_url", "tail_nonebot_log_lines"]
