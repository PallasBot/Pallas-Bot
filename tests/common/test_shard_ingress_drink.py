from __future__ import annotations

from types import SimpleNamespace

from pallas.core.platform.ingress.policy_registry import clear_ingress_policy_cache, text_matches_plugin_fanout


def _stub_drink_plugin(monkeypatch) -> None:
    plugins = [
        SimpleNamespace(
            name="drink",
            metadata=SimpleNamespace(
                extra={
                    "ingress_fanout": {
                        "scope": "always",
                        "plaintexts": [
                            "牛牛醒一醒",
                            "牛牛别喝了",
                        ],
                    }
                }
            ),
        )
    ]
    monkeypatch.setattr("pallas.core.platform.ingress.policy_registry.get_loaded_plugins", lambda: plugins)
    clear_ingress_policy_cache()


def test_drink_fanout_policy_commands(monkeypatch) -> None:
    _stub_drink_plugin(monkeypatch)
    assert not text_matches_plugin_fanout("牛牛喝酒", "drink")
    assert not text_matches_plugin_fanout("牛牛干杯", "drink")
    assert not text_matches_plugin_fanout("牛牛继续喝", "drink")
    assert text_matches_plugin_fanout("牛牛醒一醒", "drink")
    assert text_matches_plugin_fanout("牛牛别喝了", "drink")
    assert not text_matches_plugin_fanout("牛牛", "drink")
    assert not text_matches_plugin_fanout("牛牛喝酒呀", "drink")


def test_ingress_fanout_whitelist_does_not_need_drink(monkeypatch) -> None:
    from pallas.core.platform.ingress.config import clear_ingress_fanout_config_cache
    from pallas.core.platform.ingress.fanout_bypass import is_ingress_fanout_plaintext

    _stub_drink_plugin(monkeypatch)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯" if name == "PALLAS_INGRESS_FANOUT_GREETING" else default,
    )
    clear_ingress_fanout_config_cache()
    assert not is_ingress_fanout_plaintext("牛牛喝酒")
    assert not text_matches_plugin_fanout("牛牛喝酒", "drink")
