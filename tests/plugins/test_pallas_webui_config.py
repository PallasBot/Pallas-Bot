from src.plugins.pallas_webui.config import Config


def test_pallas_webui_dev_mode() -> None:
    assert Config().pallas_webui_dev_mode is False
    assert Config(pallas_webui_dev_mode=True).pallas_webui_dev_mode is True
