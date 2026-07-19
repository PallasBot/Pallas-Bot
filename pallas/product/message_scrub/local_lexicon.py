"""本地词库：环境变量子串 + 可选词表文件，Aho-Corasick 热更新。"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from nonebot import logger

from .aho_corasick import AhoCorasick
from .config import get_message_scrub_config

_lock = Lock()
_ac: AhoCorasick | None = None
_cached_sig: tuple[float | None, str, str] | None = None


def reload_local_lexicon_caches() -> None:
    """清空缓存，下次匹配时重建。"""
    global _ac, _cached_sig
    with _lock:
        _ac = None
        _cached_sig = None


def _env_substrings_lower() -> list[str]:
    raw = get_message_scrub_config().inbound_filter_substrings
    if not raw:
        return []
    return [p.lower() for p in raw.split(",") if p.strip()]


def _lexicon_path() -> str:
    return get_message_scrub_config().scrub_lexicon_path


def _read_lexicon_file_lines(path: str) -> list[str]:
    try:
        with Path(path).open(encoding="utf-8") as f:
            lines: list[str] = []
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                lines.append(s.lower())
            return lines
    except OSError as exc:
        logger.warning("message_scrub lexicon read failed path={} err={}", path, exc)
        return []


def _file_mtime(path: str) -> float | None:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _all_patterns_lower() -> list[str]:
    cfg = get_message_scrub_config()
    merged: list[str] = []
    merged.extend(_env_substrings_lower())
    path = cfg.scrub_lexicon_path
    if path:
        merged.extend(_read_lexicon_file_lines(path))
    extra = cfg.scrub_lexicon_extra
    if extra:
        for part in extra.split(","):
            s = part.strip().lower()
            if s:
                merged.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for p in merged:
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _current_cache_sig() -> tuple[float | None, str, str]:
    cfg = get_message_scrub_config()
    path = cfg.scrub_lexicon_path
    mtime = _file_mtime(path) if path else None
    return (mtime, cfg.inbound_filter_substrings, cfg.scrub_lexicon_extra)


def _get_automaton() -> AhoCorasick | None:
    global _ac, _cached_sig
    sig = _current_cache_sig()
    with _lock:
        if _cached_sig == sig and _ac is not None:
            return _ac
        pats = _all_patterns_lower()
        _ac = AhoCorasick(pats) if pats else None
        _cached_sig = sig
        return _ac


def local_lexicon_hits(*, plain_text: str, raw_message: str) -> bool:
    """仅本地词库：明文或 raw任一命中即 True。"""
    ac = _get_automaton()
    if ac is None:
        return False
    hay_plain = (plain_text or "").lower()
    hay_raw = (raw_message or "").lower()
    return ac.contains(hay_plain) or ac.contains(hay_raw)
