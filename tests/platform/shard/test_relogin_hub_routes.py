from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.core.platform.plugin_runtime.resolve import bundled_or_extra_module_prefix
from pallas.core.platform.shard.coord.relogin_hub_routes import (
    ReloginMessageBody,
    hub_relogin_message,
)
from pallas.core.platform.shard.coord.relogin_payload import ReloginHandleResult


@pytest.mark.asyncio
async def test_hub_relogin_message_imports_service_via_plugin_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_handle_relogin_message(**kwargs):
        calls.append((kwargs["bot_id"], kwargs["user_id"]))
        return ReloginHandleResult(session_active=True)

    def fake_import_plugin_submodule(plugin_id: str, submodule: str):
        assert plugin_id == "relogin_bot"
        assert submodule == "service"
        return SimpleNamespace(handle_relogin_message=fake_handle_relogin_message)

    monkeypatch.setattr(
        "pallas.core.platform.shard.coord.relogin_hub_routes.import_plugin_submodule",
        fake_import_plugin_submodule,
    )

    payload = await hub_relogin_message(ReloginMessageBody(bot_id=" 123 ", user_id=" 456 ", text="牛牛重新上号"))

    assert calls == [("123", "456")]
    assert payload == {
        "replies": [],
        "session_active": True,
        "reject_hint": None,
    }


def test_relogin_resolver_uses_canonical_direct_module_when_available() -> None:
    pytest.importorskip("pallas_plugin_relogin_bot")
    assert bundled_or_extra_module_prefix("relogin_bot") == "pallas_plugin_relogin_bot"
