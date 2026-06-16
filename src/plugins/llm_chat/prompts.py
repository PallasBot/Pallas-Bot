from __future__ import annotations

from pathlib import Path
from threading import Lock

from src.foundation.config.repo_settings import repo_root

from .config import get_llm_chat_config

_lock = Lock()
_cached_path: Path | None = None
_cached_mtime: float | None = None
_cached_text: str = ""


def clear_system_prompt_cache() -> None:
    global _cached_path, _cached_mtime, _cached_text
    with _lock:
        _cached_path = None
        _cached_mtime = None
        _cached_text = ""


def resolve_system_prompt_path() -> Path:
    cfg = get_llm_chat_config()
    custom = (cfg.llm_chat_system_prompt_path or "").strip()
    if custom:
        path = Path(custom)
        if not path.is_absolute():
            path = repo_root() / custom
        return path
    return Path(__file__).resolve().parent / "system_prompt.txt"


def get_system_prompt() -> str:
    global _cached_path, _cached_mtime, _cached_text
    path = resolve_system_prompt_path()
    with _lock:
        if not path.is_file():
            return ""
        mtime = path.stat().st_mtime
        if path != _cached_path or mtime != _cached_mtime:
            _cached_text = path.read_text(encoding="utf-8").strip()
            _cached_path = path
            _cached_mtime = mtime
        return _cached_text
