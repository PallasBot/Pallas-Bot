from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.platform.ingress.config import clear_ingress_fanout_config_cache
from src.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim
from src.platform.ingress.plugin_command_plaintext import clear_plugin_command_plaintext_cache
from src.platform.ingress.policy_registry import clear_ingress_policy_cache


@pytest.fixture(autouse=True)
def _clear_fanout_cache():
    clear_ingress_fanout_config_cache()
    clear_plugin_command_plaintext_cache()
    clear_ingress_policy_cache()
    yield
    clear_ingress_fanout_config_cache()
    clear_plugin_command_plaintext_cache()
    clear_ingress_policy_cache()


def stub_fanout_plugins(monkeypatch: pytest.MonkeyPatch, *extras: dict) -> None:
    plugins = [SimpleNamespace(name=f"p{i}", metadata=SimpleNamespace(extra=extra)) for i, extra in enumerate(extras)]
    monkeypatch.setattr("src.platform.ingress.policy_registry.get_loaded_plugins", lambda: plugins)
    clear_ingress_policy_cache()


def test_unified_drink_bypasses_once_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_fanout_plugins(
        monkeypatch,
        {
            "ingress_fanout": {
                "scope": "always",
                "plaintexts": ["牛牛喝酒", "牛牛醒一醒"],
            }
        },
    )
    assert ingress_fanout_bypasses_claim("牛牛喝酒")
    assert ingress_fanout_bypasses_claim("牛牛醒一醒")


def test_dream_does_not_bypass_claim_when_sharded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    assert not ingress_fanout_bypasses_claim("牛牛做梦")
    assert not ingress_fanout_bypasses_claim("牛牛醒梦")
    assert not ingress_fanout_bypasses_claim("牛牛别做梦")


def test_greeting_fanout_texts_bypass_once_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯,牛牛赞我,赞我" if name == "PALLAS_INGRESS_FANOUT_GREETING" else default,
    )
    clear_ingress_fanout_config_cache()
    assert ingress_fanout_bypasses_claim("牛牛")
    assert ingress_fanout_bypasses_claim("帕拉斯")
    assert ingress_fanout_bypasses_claim("牛牛赞我")
    assert ingress_fanout_bypasses_claim("赞我")


def test_help_commands_bypass_once_claim_when_unified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLAS_SHARD_ENABLED", raising=False)
    monkeypatch.delenv("PALLAS_BOT_ROLE", raising=False)
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    stub_fanout_plugins(
        monkeypatch,
        {
            "ingress_fanout": {
                "scope": "unified_only",
                "prefixes": ["牛牛帮助", "牛牛开启", "牛牛关闭", "牛牛开启全部功能", "牛牛关闭全部功能"],
            }
        },
    )
    assert ingress_fanout_bypasses_claim("牛牛帮助")
    assert ingress_fanout_bypasses_claim("牛牛帮助 1")
    assert ingress_fanout_bypasses_claim("/牛牛帮助 复读")
    assert ingress_fanout_bypasses_claim("牛牛开启 复读")
    assert ingress_fanout_bypasses_claim("牛牛关闭全部功能")


def test_help_commands_do_not_bypass_when_sharded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    stub_fanout_plugins(
        monkeypatch,
        {
            "ingress_fanout": {
                "scope": "unified_only",
                "prefixes": ["牛牛帮助", "牛牛开启", "牛牛关闭"],
            }
        },
    )
    assert not ingress_fanout_bypasses_claim("牛牛帮助")
    assert not ingress_fanout_bypasses_claim("牛牛帮助 1")
    assert not ingress_fanout_bypasses_claim("牛牛开启 复读")
    assert not ingress_fanout_bypasses_claim("牛牛关闭全部功能")


def test_plugin_commands_do_not_bypass_once_claim_when_unified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLAS_SHARD_ENABLED", raising=False)
    monkeypatch.delenv("PALLAS_BOT_ROLE", raising=False)
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    fake_plugins = [
        SimpleNamespace(
            name="draw",
            metadata=SimpleNamespace(extra={"menu_data": [{"trigger_condition": "牛牛画画 …"}]}),
        ),
        SimpleNamespace(
            name="sing",
            metadata=SimpleNamespace(
                extra={
                    "menu_data": [
                        {"trigger_condition": "牛牛唱歌 歌曲名 [key=±N]"},
                        {"trigger_condition": "牛牛MAA状态"},
                    ]
                }
            ),
        ),
        SimpleNamespace(
            name="bot_status",
            metadata=SimpleNamespace(extra={"menu_data": [{"trigger_condition": "牛牛在吗"}]}),
        ),
    ]
    monkeypatch.setattr(
        "src.platform.ingress.plugin_command_plaintext.get_loaded_plugins",
        lambda: fake_plugins,
    )
    monkeypatch.setattr(
        "src.platform.ingress.plugin_command_plaintext.TrieRule.prefix.longest_prefix",
        lambda text: SimpleNamespace(key="牛牛画画") if text.startswith("牛牛画画") else None,
    )
    clear_plugin_command_plaintext_cache()

    assert not ingress_fanout_bypasses_claim("牛牛画画")
    assert not ingress_fanout_bypasses_claim("牛牛唱歌 海阔天空")
    assert not ingress_fanout_bypasses_claim("牛牛MAA状态")
    assert not ingress_fanout_bypasses_claim("牛牛在吗")


def _stub_plugin_command_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_plugins = [
        SimpleNamespace(
            name="draw",
            metadata=SimpleNamespace(extra={"menu_data": [{"trigger_condition": "牛牛画画 …"}]}),
        ),
    ]
    monkeypatch.setattr(
        "src.platform.ingress.plugin_command_plaintext.get_loaded_plugins",
        lambda: fake_plugins,
    )
    monkeypatch.setattr(
        "src.platform.ingress.plugin_command_plaintext.TrieRule.prefix.longest_prefix",
        lambda text: SimpleNamespace(key="牛牛画画") if text.startswith("牛牛画画") else None,
    )
    clear_plugin_command_plaintext_cache()


def test_plugin_commands_do_not_bypass_when_sharded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    _stub_plugin_command_plaintext(monkeypatch)
    assert not ingress_fanout_bypasses_claim("牛牛画画")


def test_shard_bot_count_fanout_with_trailing_punct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    stub_fanout_plugins(
        monkeypatch,
        {
            "ingress_fanout": {
                "scope": "shard_only",
                "plaintexts": ["牛牛报数", "牛牛出列"],
                "normalize_trailing_punct": True,
            }
        },
    )
    assert ingress_fanout_bypasses_claim("牛牛报数！")
    assert ingress_fanout_bypasses_claim("牛牛出列?")


def test_cage_regex_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_fanout_plugins(
        monkeypatch,
        {"ingress_fanout": {"scope": "always", "regexes": [r"^八角笼(?:牛|斗)(?:\s*\d{1,2}\s*(?:幕|回合))?\s*$"]}},
    )
    assert ingress_fanout_bypasses_claim("八角笼牛")
    assert ingress_fanout_bypasses_claim("八角笼斗 3幕")
