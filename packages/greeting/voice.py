import random
from pathlib import Path

from pallas.core.foundation.paths import resource_dir

voice_set = {
    "任命助理",
    "交谈1",
    "交谈2",
    "交谈3",
    "晋升后交谈1",
    "晋升后交谈2",
    "信赖提升后交谈1",
    "信赖提升后交谈2",
    "信赖提升后交谈3",
    "闲置",
    "干员报到",
    "精英化晋升1",
    "精英化晋升2",
    "编入队伍",
    "任命队长",
    "戳一下",
    "信赖触摸",
    "问候",
}

voices_source = resource_dir("voices")
_extra_dir = voices_source / "extra"

_extra_cache: set[str] | None = None
_extra_mtime: float | None = None


def _load_extra_voices() -> set[str]:
    """从 extra 目录加载侧载语音集合，使用 mtime 缓存避免频繁磁盘扫描。"""
    global _extra_cache, _extra_mtime
    if not _extra_dir.exists():
        _extra_cache = set()
        _extra_mtime = None
        return _extra_cache

    current_mtime = _extra_dir.stat().st_mtime
    if _extra_cache is None or _extra_mtime != current_mtime:
        _extra_cache = {f.stem for f in _extra_dir.iterdir() if f.suffix == ".wav"}
        _extra_mtime = current_mtime
    return _extra_cache


def _is_voice_available(voice_name: str) -> bool:
    """检查语音是否可用。"""
    if voice_name in voice_set:
        return True
    return voice_name in _load_extra_voices()


def get_voice_filepath(operator, voice_name) -> Path | None:
    if not _is_voice_available(voice_name):
        return None
    f = voices_source / operator / f"{voice_name}.wav"
    if f.exists():
        return f
    extra_f = _extra_dir / f"{voice_name}.wav"
    return extra_f if extra_f.exists() else None


def get_random_voice(operator, ranges) -> Path | None:
    extra_set = _load_extra_voices()
    available = [r for r in ranges if r in voice_set or r in extra_set]
    if not available:
        return None
    key = random.choice(available)
    return get_voice_filepath(operator, key)
