import pytest

from src.platform.ingress.config import clear_ingress_fanout_config_cache
from src.platform.ingress.fanout_bypass import is_greeting_fanout_plaintext, is_ingress_fanout_plaintext


@pytest.fixture(autouse=True)
def _clear_fanout_cache():
    clear_ingress_fanout_config_cache()
    yield
    clear_ingress_fanout_config_cache()


def test_fanout_texts_default(monkeypatch):
    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯,牛牛报数,牛牛出列"
        if name == "PALLAS_INGRESS_FANOUT_GREETING"
        else default,
    )
    clear_ingress_fanout_config_cache()
    assert is_ingress_fanout_plaintext("牛牛")
    assert is_ingress_fanout_plaintext("帕拉斯")
    assert is_ingress_fanout_plaintext("牛牛报数")
    assert not is_ingress_fanout_plaintext("牛牛喝酒")
    assert is_greeting_fanout_plaintext("牛牛")


def test_fanout_texts_from_env(monkeypatch):
    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛赞我,赞我" if name == "PALLAS_INGRESS_FANOUT_GREETING" else default,
    )
    clear_ingress_fanout_config_cache()
    assert is_ingress_fanout_plaintext("牛牛赞我")
    assert is_ingress_fanout_plaintext("赞我")
    assert not is_ingress_fanout_plaintext("牛牛报数")
    assert not is_greeting_fanout_plaintext("牛牛赞我")
