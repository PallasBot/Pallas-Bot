from packages.pb_core.status import format_runtime_status_text


def test_format_runtime_status_text_includes_version_line():
    text = format_runtime_status_text()
    assert text.startswith("版本：")
    assert "运行模式" in text or "分片" in text
