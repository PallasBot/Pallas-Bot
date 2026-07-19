"""taken_name：Mongo BSON 要求 string key（issue #228）。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_update_taken_name_uses_string_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.foundation.config import BotConfig

    stored: dict[str, object] = {}

    async def fake_find(self, key: str):  # noqa: ANN001
        assert key == "taken_name"
        return {568530739: 111, "999": 222}

    async def fake_update(self, key: str, value):  # noqa: ANN001
        assert key == "taken_name"
        stored["value"] = value

    monkeypatch.setattr(BotConfig, "_find", fake_find)
    monkeypatch.setattr(BotConfig, "_update", fake_update)

    cfg = BotConfig(3791836305, 568530739)
    await cfg.update_taken_name(3654501983)
    assert stored["value"] == {"568530739": 3654501983, "999": 222}
    assert all(isinstance(k, str) for k in stored["value"])


@pytest.mark.asyncio
async def test_taken_name_reads_str_or_int_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.foundation.config import BotConfig

    async def fake_find_str(self, key: str):  # noqa: ANN001
        return {"42": 1001}

    monkeypatch.setattr(BotConfig, "_find", fake_find_str)
    assert await BotConfig(1, 42).taken_name() == 1001

    async def fake_find_int(self, key: str):  # noqa: ANN001
        return {42: 1002}

    monkeypatch.setattr(BotConfig, "_find", fake_find_int)
    assert await BotConfig(1, 42).taken_name() == 1002
