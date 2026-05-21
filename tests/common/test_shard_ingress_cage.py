from __future__ import annotations

from src.common.ingress.cage_plaintext import is_cage_plaintext


def test_cage_plaintext_variants() -> None:
    assert is_cage_plaintext("八角笼牛")
    assert is_cage_plaintext("八角笼斗")
    assert is_cage_plaintext("八角笼牛 7幕")
    assert is_cage_plaintext("八角笼斗 3回合")
    assert not is_cage_plaintext("八角笼")


def test_ingress_fanout_whitelist_does_not_need_cage(monkeypatch) -> None:
    from src.common.ingress.config import clear_ingress_fanout_config_cache
    from src.common.shard.ingress_fanout import is_ingress_fanout_plaintext

    monkeypatch.setattr(
        "src.common.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯"
        if name == "PALLAS_INGRESS_FANOUT_GREETING"
        else default,
    )
    clear_ingress_fanout_config_cache()
    assert not is_ingress_fanout_plaintext("八角笼牛")
    assert is_cage_plaintext("八角笼牛")
