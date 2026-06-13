from __future__ import annotations

import pytest

from src.features.corpus.config import CorpusConfig
from src.foundation.db.modules import Answer, Context


@pytest.mark.asyncio
async def test_mirror_insert_forces_community_group_id_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import write_fanout as mod

    inserted: list[int] = []

    class FakeCommunity:
        async def insert(self, context: Context) -> None:
            inserted.extend(int(ans.group_id) for ans in context.answers)

    monkeypatch.setattr(mod, "community_contribute_enabled", lambda cfg: True)

    ctx = Context.model_construct(
        keywords="kw",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="a", group_id=12345, count=1, time=1, messages=["hi"])],
        ban=[],
        clear_time=0,
    )
    cfg = CorpusConfig(community_contribute=True)
    await mod.mirror_insert(fed=None, community=FakeCommunity(), cfg=cfg, context=ctx)
    assert inserted == [0]
