from __future__ import annotations

import httpx
import pytest

from pallas.core.platform.shard.coord.relogin_constants import (
    RELOGIN_FORWARD_TIMEOUT_SEC,
    RELOGIN_HUB_PATH,
)


def test_relogin_forward_timeout_covers_hub_side_waits() -> None:
    # process 90 + qr 60 + connect 90 + docker 开销，须 > 旧值 130
    assert RELOGIN_FORWARD_TIMEOUT_SEC >= 300


@pytest.mark.asyncio
async def test_forward_relogin_to_hub_uses_extended_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.shard.coord import relogin_worker_forward as mod

    captured: dict[str, object] = {}

    class FakeSettings:
        hub_port = 7969

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"replies": [], "session_active": False, "reject_hint": None}

    class FakeClient:
        def __init__(self, *, timeout: httpx.Timeout, **_kwargs):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url: str, json: dict):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: FakeSettings())
    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)

    result = await mod.forward_relogin_to_hub(bot_id="1", user_id="2", text="牛牛重新上号")

    assert result is not None
    assert captured["url"] == f"http://127.0.0.1:7969{RELOGIN_HUB_PATH}"
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert float(timeout.read) >= 300  # type: ignore[arg-type]
