import pytest

from pallas.core.commands.matcher import PluginCommand, _plugin_tag_from_command_id


def test_plugin_tag_from_command_id():
    assert _plugin_tag_from_command_id("pb_core.status") == "pb_core"
    assert _plugin_tag_from_command_id("praise_me.praise") == "praise_me"
    assert _plugin_tag_from_command_id("") == "plugin"


class _FakeMatcher:
    def handle(self):
        def register(handler):
            self.wrapper = handler
            return handler

        return register


@pytest.mark.parametrize("default_cd_sec", [0, None])
@pytest.mark.asyncio
async def test_default_cooldown_override_applies_to_primary_and_alias(monkeypatch, default_cd_sec):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pallas.core.commands.matcher as module
    import pallas.core.limits.cooldown as cooldown

    configured_cds = []
    checked_keys = []
    refreshes = []
    config_reads = []

    class Config:
        async def is_cooldown(self, key):
            checked_keys.append(key)
            return True

        async def refresh_cooldown(self, key):
            refreshes.append(key)

    def get_limits_config():
        config_reads.append(True)
        return SimpleNamespace(command_limit_overrides={"test.shared": 9})

    monkeypatch.setattr(cooldown, "get_command_limits_config", get_limits_config)

    def config_for_event(_event, cd_sec):
        configured_cds.append(cd_sec)
        return Config()

    monkeypatch.setattr(cooldown, "config_for_message_event", config_for_event)
    monkeypatch.setattr(module, "PluginHandlerContext", lambda **_kwargs: type("Context", (), {"user_id": "1"})())
    handler = AsyncMock()
    matchers = [_FakeMatcher(), _FakeMatcher()]
    for matcher in matchers:
        PluginCommand(
            matcher=matcher,
            command_id="test.shared",
            default_cd_sec=default_cd_sec,
            plugin_tag="test",
        ).handle(handler)

    for matcher in matchers:
        await matcher.wrapper(object(), object())

    assert configured_cds == [9, 9, 9, 9]
    assert checked_keys == ["cmd_limit:test.shared"] * 2
    assert refreshes == ["cmd_limit:test.shared"] * 2
    assert len(config_reads) == 2
    assert handler.await_count == 2


@pytest.mark.asyncio
async def test_denied_cooldown_does_not_refresh_or_run_handler(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pallas.core.commands.matcher as module
    import pallas.core.limits.cooldown as cooldown

    class Config:
        async def is_cooldown(self, _key):
            return False

        async def refresh_cooldown(self, _key):
            pytest.fail("denied command must not refresh cooldown")

    monkeypatch.setattr(
        cooldown,
        "get_command_limits_config",
        lambda: SimpleNamespace(command_limit_overrides={"test.cmd": 9}),
    )
    monkeypatch.setattr(cooldown, "config_for_message_event", lambda _event, _cd: Config())
    monkeypatch.setattr(module, "PluginHandlerContext", lambda **_kwargs: type("Context", (), {"user_id": "1"})())
    handler = AsyncMock()
    matcher = _FakeMatcher()
    PluginCommand(matcher=matcher, command_id="test.cmd", default_cd_sec=0, plugin_tag="test").handle(handler)

    await matcher.wrapper(object(), object())

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_effective_cooldown_disabled_does_not_block(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pallas.core.commands.matcher as module
    import pallas.core.limits.cooldown as cooldown

    monkeypatch.setattr(
        cooldown,
        "get_command_limits_config",
        lambda: SimpleNamespace(command_limit_overrides={"test.cmd": 0}),
    )
    monkeypatch.setattr(
        cooldown,
        "config_for_message_event",
        lambda *_args: pytest.fail("disabled cooldown must not access storage"),
    )
    monkeypatch.setattr(module, "PluginHandlerContext", lambda **_kwargs: type("Context", (), {"user_id": "1"})())
    handler = AsyncMock()
    matcher = _FakeMatcher()
    PluginCommand(matcher=matcher, command_id="test.cmd", default_cd_sec=9, plugin_tag="test").handle(handler)

    await matcher.wrapper(object(), object())

    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_default_and_override_runs_handler_without_cooldown_storage(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pallas.core.commands.matcher as module
    import pallas.core.limits.cooldown as cooldown
    import pallas.core.limits.schema as limits_schema

    monkeypatch.setattr(
        cooldown,
        "get_command_limits_config",
        lambda: SimpleNamespace(command_limit_overrides={}),
    )
    monkeypatch.setattr(limits_schema, "merged_default_command_limits", dict)
    monkeypatch.setattr(
        cooldown,
        "config_for_message_event",
        lambda *_args: pytest.fail("missing cooldown must not access storage"),
    )
    monkeypatch.setattr(module, "PluginHandlerContext", lambda **_kwargs: type("Context", (), {"user_id": "1"})())
    handler = AsyncMock()
    matcher = _FakeMatcher()
    PluginCommand(matcher=matcher, command_id="test.cmd", default_cd_sec=None, plugin_tag="test").handle(handler)

    await matcher.wrapper(object(), object())

    handler.assert_awaited_once()
