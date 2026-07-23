from packages.pb_webui.config import Config


def test_pallas_webui_dev_mode() -> None:
    assert Config().pallas_webui_dev_mode is False
    assert Config(pallas_webui_dev_mode=True).pallas_webui_dev_mode is True


def test_pallas_webui_frontend_default_react() -> None:
    assert Config().pallas_webui_frontend == "react"
    assert Config(pallas_webui_frontend="vue").pallas_webui_frontend == "vue"
