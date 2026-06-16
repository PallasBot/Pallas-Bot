from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

from src.features.persona.compile_persona_prompt import (
    clear_base_system_prompt_cache,
    load_base_system_prompt,
    resolve_base_system_prompt_path,
)

from .config import get_ollama_config

if TYPE_CHECKING:
    from pathlib import Path

_lock = Lock()


def clear_system_prompt_cache() -> None:
    with _lock:
        clear_base_system_prompt_cache()


def resolve_system_prompt_path() -> Path:
    cfg = get_ollama_config()
    return resolve_base_system_prompt_path(cfg.ollama_system_prompt_path or None)


def get_system_prompt() -> str:
    cfg = get_ollama_config()
    with _lock:
        return load_base_system_prompt(custom_path=cfg.ollama_system_prompt_path or None)
