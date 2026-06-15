"""语料多源工厂。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.features.corpus.community_source import RemoteCorpusRepository
from src.features.corpus.composite_repo import CompositeContextRepository
from src.features.corpus.config import (
    corpus_composite_enabled,
    fed_configured,
    get_corpus_config,
    is_community_corpus_wanted,
    resolve_enabled,
    resolved_community_api_base_urls,
    resolved_community_token,
)

if TYPE_CHECKING:
    from src.foundation.db.repository import ContextRepository


def build_community_repository() -> ContextRepository | None:
    cfg = get_corpus_config()
    if not is_community_corpus_wanted(cfg):
        return None
    api_bases = resolved_community_api_base_urls()
    token = resolved_community_token()
    if not api_bases or not token:
        return None
    return RemoteCorpusRepository(api_bases=api_bases, token=token)


def build_fed_repository() -> ContextRepository | None:
    cfg = get_corpus_config()
    if not resolve_enabled(cfg.fed_enabled, configured=fed_configured()):
        return None
    # 联邦 PG 第二连接在后续 Phase 接入
    return None


def maybe_wrap_composite(local: ContextRepository) -> ContextRepository:
    if not corpus_composite_enabled():
        return local
    fed = build_fed_repository()
    community = build_community_repository()
    if fed is None and community is None:
        return local
    return CompositeContextRepository(local, fed=fed, community=community)
