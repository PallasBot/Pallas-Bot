from packages.pb_webui.config import Config


def test_pallas_webui_dev_mode() -> None:
    assert Config().pallas_webui_dev_mode is False
    assert Config(pallas_webui_dev_mode=True).pallas_webui_dev_mode is True


def test_pallas_webui_frontend_default_vue() -> None:
    assert Config().pallas_webui_frontend == "vue"
    assert Config(pallas_webui_frontend="react").pallas_webui_frontend == "react"
