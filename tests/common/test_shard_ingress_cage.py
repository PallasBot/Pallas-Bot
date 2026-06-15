from __future__ import annotations

from types import SimpleNamespace

from src.platform.ingress.policy_registry import clear_ingress_policy_cache, text_matches_plugin_fanout


def _stub_duel_plugin(monkeypatch) -> None:
    plugins = [
        SimpleNamespace(
            name="duel",
            metadata=SimpleNamespace(
                extra={
                    "ingress_fanout": {
                        "scope": "always",
                        "regexes": [r"^八角笼(?:牛|斗)(?:\s*\d{1,2}\s*(?:幕|回合))?\s*$"],
                    }
                }
            ),
        )
    ]
    monkeypatch.setattr("src.platform.ingress.policy_registry.get_loaded_plugins", lambda: plugins)
    clear_ingress_policy_cache()


def test_cage_fanout_policy_variants(monkeypatch) -> None:
    _stub_duel_plugin(monkeypatch)
    assert text_matches_plugin_fanout("八角笼牛", "duel")
    assert text_matches_plugin_fanout("八角笼斗", "duel")
    assert text_matches_plugin_fanout("八角笼牛 7幕", "duel")
    assert text_matches_plugin_fanout("八角笼斗 3回合", "duel")
    assert not text_matches_plugin_fanout("八角笼", "duel")


def test_ingress_fanout_whitelist_does_not_need_cage(monkeypatch) -> None:
    from src.platform.ingress.config import clear_ingress_fanout_config_cache
    from src.platform.shard.ingress_fanout import is_ingress_fanout_plaintext

    _stub_duel_plugin(monkeypatch)
    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯" if name == "PALLAS_INGRESS_FANOUT_GREETING" else default,
    )
    clear_ingress_fanout_config_cache()
    assert not is_ingress_fanout_plaintext("八角笼牛")
    assert text_matches_plugin_fanout("八角笼牛", "duel")
