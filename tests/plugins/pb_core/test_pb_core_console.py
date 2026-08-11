from unittest.mock import MagicMock, patch

from packages.pb_core.console import format_console_hint_text, format_plugins_summary_text


def test_console_hint_uses_labeled_fields():
    driver = MagicMock()
    driver.config.host = "127.0.0.1"
    driver.config.port = 8080
    with patch("packages.pb_core.console.get_driver", return_value=driver):
        text = format_console_hint_text()

    assert text.startswith("【牛牛控制台】")
    assert "地址：" in text
    assert "登录：" in text


def test_plugins_summary_uses_sections():
    text = format_plugins_summary_text(loaded_names={"pb_core"})

    assert text.startswith("【牛牛插件】")
    assert "Core：" in text
    assert "扩展：" in text
