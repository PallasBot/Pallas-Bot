from __future__ import annotations

from types import SimpleNamespace

from pallas.core.platform.ingress.policy_registry import clear_ingress_policy_cache, text_matches_plugin_fanout


def _stub_roulette_plugin(monkeypatch) -> None:
    plugins = [
        SimpleNamespace(
            name="roulette",
            metadata=SimpleNamespace(
                extra={
                    "ingress_fanout": {
                        "scope": "always",
                        "plaintexts": [
                            "牛牛轮盘",
                            "牛牛轮盘踢人",
                            "牛牛轮盘禁言",
                            "牛牛踢人轮盘",
                            "牛牛禁言轮盘",
                            "牛牛开枪",
                        ],
                        "prefixes": ["牛牛救一下", "牛牛补一枪"],
                    }
                }
            ),
        )
    ]
    monkeypatch.setattr("pallas.core.platform.ingress.policy_registry.get_loaded_plugins", lambda: plugins)
    clear_ingress_policy_cache()


def test_roulette_fanout_policy_commands(monkeypatch) -> None:
    _stub_roulette_plugin(monkeypatch)
    assert text_matches_plugin_fanout("牛牛轮盘", "roulette")
    assert text_matches_plugin_fanout("牛牛轮盘踢人", "roulette")
    assert text_matches_plugin_fanout("牛牛轮盘禁言", "roulette")
    assert text_matches_plugin_fanout("牛牛开枪", "roulette")
    assert text_matches_plugin_fanout("牛牛救一下", "roulette")
    assert text_matches_plugin_fanout("牛牛救一下 @某人", "roulette")
    assert text_matches_plugin_fanout("牛牛补一枪", "roulette")
    assert not text_matches_plugin_fanout("牛牛", "roulette")
    assert not text_matches_plugin_fanout("参与轮盘", "roulette")
