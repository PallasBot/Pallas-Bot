from __future__ import annotations

from src.plugins.dream.commands import is_dream_plaintext


def test_dream_plaintext_commands() -> None:
    assert is_dream_plaintext("牛牛做梦")
    assert is_dream_plaintext("牛牛醒梦")
    assert is_dream_plaintext("牛牛别做梦")
    assert not is_dream_plaintext("牛牛")
    assert not is_dream_plaintext("牛牛做梦呀")


def test_ingress_fanout_whitelist_does_not_need_dream(monkeypatch) -> None:
    from src.platform.ingress.config import clear_ingress_fanout_config_cache
    from src.platform.ingress.fanout_bypass import is_ingress_fanout_plaintext

    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯" if name == "PALLAS_INGRESS_FANOUT_GREETING" else default,
    )
    clear_ingress_fanout_config_cache()
    assert not is_ingress_fanout_plaintext("牛牛做梦")
    assert is_dream_plaintext("牛牛做梦")
