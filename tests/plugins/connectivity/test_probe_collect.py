import asyncio

from src.plugins.connectivity.probe_collect import probe_sing_server, sing_probe_urls
from src.plugins.sing.config import Config


def test_sing_probe_urls() -> None:
    urls = sing_probe_urls("http://127.0.0.1:9099")
    assert urls == [("健康检查", "http://127.0.0.1:9099/health")]


def test_probe_sing_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.plugins.sing.config.get_sing_config",
        lambda: Config(sing_enable=False),
    )
    results = asyncio.run(probe_sing_server())
    assert len(results) == 1
    assert results[0].error == "未启用 sing_enable"
