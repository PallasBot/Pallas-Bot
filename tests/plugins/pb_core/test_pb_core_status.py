from packages.pb_core.status import _format_uptime, format_runtime_status_text


def test_format_runtime_status_text_includes_version_line():
    text = format_runtime_status_text(self_id="123456")
    assert text.startswith("版本：")
    assert "本机 QQ：123456" in text
    assert "运行时长：" in text
    assert "运行模式" in text or "分片" in text


def test_format_uptime():
    assert _format_uptime(65) == "1分5秒"
    assert _format_uptime(3661) == "1小时1分1秒"
