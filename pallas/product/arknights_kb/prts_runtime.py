"""内建 PRTS 语料的显式状态与更新入口。"""

from __future__ import annotations

from typing import Any

from pallas.core.foundation.paths import DATA_ROOT
from pallas.product.arknights_kb.config import get_arknights_kb_config
from pallas.product.arknights_kb.prts_corpus import CorpusStore, auto_update_if_needed, parse_pack_ids

CORPUS_DIR = DATA_ROOT / "prts_corpus"
_STORE: CorpusStore | None = None


def corpus_store() -> CorpusStore:
    global _STORE
    if _STORE is None:
        cfg = get_arknights_kb_config()
        _STORE = CorpusStore(
            CORPUS_DIR,
            cache_max_bytes=cfg.prts_corpus_cache_max_mb * 1024 * 1024,
            query_max_bytes=cfg.prts_corpus_query_max_mb * 1024 * 1024,
        )
    return _STORE


def corpus_status() -> dict[str, Any]:
    return corpus_store().status()


def update_corpus() -> dict[str, Any]:
    cfg = get_arknights_kb_config()
    packs = parse_pack_ids(cfg.prts_corpus_packs, include_endfield=cfg.prts_corpus_include_endfield)
    return auto_update_if_needed(
        CORPUS_DIR,
        packs,
        timeout=cfg.prts_corpus_download_timeout_sec,
    )
