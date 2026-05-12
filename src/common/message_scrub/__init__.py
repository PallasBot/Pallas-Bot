from __future__ import annotations

from .api_client import api_scrub_blocked
from .local_lexicon import local_lexicon_hits, reload_local_lexicon_caches


def reload_message_scrub_caches() -> None:
    """热重载本地词库（环境变量、词表文件 mtime 变化会自动重建）。"""
    reload_local_lexicon_caches()


def is_message_scrub_blocked_sync(*, plain_text: str, raw_message: str) -> bool:
    """仅本地词库（同步，无网络）。"""
    return local_lexicon_hits(plain_text=plain_text, raw_message=raw_message)


async def is_message_scrub_blocked_async(*, plain_text: str, raw_message: str) -> bool:
    """本地词库优先；未命中时再调用可选 API。"""
    if local_lexicon_hits(plain_text=plain_text, raw_message=raw_message):
        return True
    return await api_scrub_blocked(plain_text=plain_text, raw_message=raw_message)
