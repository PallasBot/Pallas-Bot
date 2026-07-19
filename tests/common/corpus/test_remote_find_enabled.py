from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.corpus.composite_repo import CompositeContextRepository
from pallas.product.corpus.config import CorpusConfig, remote_corpus_find_enabled, remote_corpus_find_mode


def test_remote_find_auto_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.corpus.config.setting_str",
        lambda name, default="": default,
    )
    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    assert remote_corpus_find_enabled() is False


def test_remote_find_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.corpus.config.setting_str",
        lambda name, default="": "false" if name == "PALLAS_CORPUS_REMOTE_FIND_ENABLED" else default,
    )
    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    assert remote_corpus_find_mode() == "off"
    assert remote_corpus_find_enabled() is False


def test_remote_find_true_is_prefetch_not_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.corpus.config.setting_str",
        lambda name, default="": "true" if name == "PALLAS_CORPUS_REMOTE_FIND_ENABLED" else default,
    )
    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    assert remote_corpus_find_mode() == "prefetch"
    assert remote_corpus_find_enabled() is False


@pytest.mark.asyncio
async def test_composite_skips_remote_find_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.corpus.find_cache import reset_find_cache_for_tests

    await reset_find_cache_for_tests()
    local = AsyncMock()
    local.find_by_keywords = AsyncMock(return_value=None)
    local.find_by_keywords_for_reply = None
    community = AsyncMock()
    community.find_by_keywords = AsyncMock(return_value=None)
    cfg = CorpusConfig(merge_order=["local", "community"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, community=community, cfg=cfg)

    async def always_remote() -> bool:
        return False

    import pallas.product.corpus.composite_repo as mod

    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda _cfg=None: "off")
    try:
        assert await repo.find_by_keywords("kw") is None
        community.find_by_keywords.assert_not_called()
    finally:
        monkeypatch.undo()
