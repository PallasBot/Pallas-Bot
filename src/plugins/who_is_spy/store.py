from __future__ import annotations

import json
import shutil
from pathlib import Path

from nonebot import logger

from src.foundation.paths import plugin_data_dir, resource_dir

DEFAULT_WORD_FILE = resource_dir("who_is_spy") / "undercover_words.json"
DATA_DIR = plugin_data_dir("who_is_spy")
WORD_FILE = DATA_DIR / "undercover_words.json"

WORD_BANK: list[tuple[str, str]] = []


def ensure_word_file() -> Path:
    if not WORD_FILE.exists() and DEFAULT_WORD_FILE.is_file():
        shutil.copyfile(DEFAULT_WORD_FILE, WORD_FILE)
        logger.info("who_is_spy: seeded word bank from {} to {}", DEFAULT_WORD_FILE, WORD_FILE)
    return WORD_FILE


def load_words_from_json(path: Path | str | None = None) -> int:
    target = Path(path) if path else ensure_word_file()
    if not target.is_file():
        return 0
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("who_is_spy: load word bank failed path={} err={}", target, exc)
        return 0

    pairs: list[tuple[str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            civilian, undercover = str(item[0]).strip(), str(item[1]).strip()
            if civilian and undercover:
                pairs.append((civilian, undercover))
    WORD_BANK[:] = pairs
    return len(pairs)


def init_store() -> None:
    ensure_word_file()
    loaded = load_words_from_json(WORD_FILE)
    if loaded:
        logger.info("who_is_spy: loaded {} word pairs from {}", loaded, WORD_FILE)
