"""内置严格下流词表：入站 message_scrub 与记忆教学审查共用。

词表来源 ``resource/message_scrub/vulgar.txt``（Sensitive-lexicon 人工审定，仅
严格级性/辱骂/迷奸/成人词）；按 mtime 缓存，文件变化下次匹配自动重建。
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from pallas.core.foundation.paths import resource_dir

if TYPE_CHECKING:
    from collections.abc import Iterable

_VULGAR_LEXICON_PATH = "message_scrub/vulgar.txt"

_lock = Lock()
_cached_sig: tuple[int, int] | None = None
_cached_negative: bool = False
_cached_words: tuple[str, ...] = ()


def _vulgar_lexicon_path() -> str:
    try:
        return str(resource_dir(*_VULGAR_LEXICON_PATH.split("/")))
    except Exception:
        return _VULGAR_LEXICON_PATH


def _read_phrases(path: str) -> list[str]:
    words: list[str] = []
    try:
        with Path(path).open(encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                words.append(s.lower())
    except OSError:
        return []
    return words


def load_vulgar_phrases() -> tuple[str, ...]:
    """读取内置下流词表；文件缺失或读失败返回空元组（不阻断业务）。

    缺失/读失败也缓存 negative（空 + 缺失标记），避免高频入站路径
    每条消息重复 stat + open 失败 IO。
    """
    global _cached_sig, _cached_negative, _cached_words
    path = _vulgar_lexicon_path()
    try:
        stat = Path(path).stat()
        sig = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        sig = None
    with _lock:
        if _cached_sig == sig and _cached_words:
            return _cached_words
        if _cached_negative and sig is None:
            return _cached_words
        words = _read_phrases(path)
        _cached_negative = not words
        _cached_sig = sig if words else None
        _cached_words = tuple(words)
        return _cached_words


def contains_vulgar_phrase(text: str) -> bool:
    """明文是否命中任一内置下流词（不区分大小写）。"""
    plain = str(text or "").strip().lower()
    if not plain:
        return False
    return any(phrase in plain for phrase in load_vulgar_phrases())


def vulgar_phrases() -> Iterable[str]:
    return load_vulgar_phrases()


def memory_guidance_block_reason(text: str) -> str | None:
    """记忆写入前的教学注入审查：命中下流词或贬损教学词且呈短判断/教学句式时返回命中词。

    入站 message_scrub 已拦掉绝大多数下流消息；此函数兜底拦「入站漏网 +
    变体绕过 + 摘要/关系笔记路径」写进记忆的判断式教学（如「X 是 Y」且 Y 为
    下流词或贬损外号词）。正常长段落群聊记录含个别贬损词不拦（无教学信号）。

    贬损组词（区/狗/猪/鸡 等）仅此处使用，不入站（用户对入站只按严格词表）。
    """
    plain = str(text or "").strip()
    if not plain:
        return None
    lower = plain.lower()
    hit = next((phrase for phrase in load_vulgar_phrases() if phrase in lower), None)
    if hit is None:
        hit = next((word for word in _MEMORY_TEACH_DEROGATORY if word in lower), None)
        if hit is not None and not _looks_like_teach_judgment(plain):
            return None
        return hit
    if len(plain) <= 24 or any(token in plain for token in _GUIDANCE_TEACH_SIGNALS):
        return hit
    return None


def _looks_like_teach_judgment(text: str) -> bool:
    """判断式/教学句式：含判断联结词或显式教学前缀。"""
    return any(token in text for token in _GUIDANCE_TEACH_SIGNALS) or "是" in text or "叫" in text


_MEMORY_TEACH_DEROGATORY = (
    "区王",
    "区宝宝",
    "大区",
    "是区",
    "是狗",
    "是猪",
    "是鸡",
    "母狗",
    "骚货",
    "贱货",
    "贱人",
)


_GUIDANCE_TEACH_SIGNALS = ("记住", "记得", "以后", "称呼", "他是", "她是")


def clear_vulgar_lexicon_cache() -> None:
    """清空词表缓存（供 reload_message_scrub_caches 调用）。"""
    global _cached_sig, _cached_negative, _cached_words
    with _lock:
        _cached_sig = None
        _cached_negative = False
        _cached_words = ()
