from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_image_cache_prune_only_runs_on_maintenance_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.handlers import scheduler as mod

    prune = AsyncMock()
    monkeypatch.setattr(mod, "prune_image_cache", prune)
    monkeypatch.setattr(mod, "repeater_maintenance_runs_on_worker", lambda: False)

    await mod.run_image_cache_prune()

    prune.assert_not_awaited()

    monkeypatch.setattr(mod, "repeater_maintenance_runs_on_worker", lambda: True)
    await mod.run_image_cache_prune()

    prune.assert_awaited_once_with()
