from packages.help.help_constants import HELP_STATUS_OFF, HELP_STATUS_ON
from packages.help.markdown_generator import (
    _is_numbered_list_block,
    _plugin_page_status_banner,
    _wrap_paragraphs_for_help_page,
    generate_plugins_markdown,
    help_list_status_mark,
)


def test_wrap_preserves_markdown_table() -> None:
    raw = "| 口令 | 说明 |\n|------|------|\n| 牛牛长草 | 完整长草 |"
    out = _wrap_paragraphs_for_help_page(raw)
    assert "| 牛牛长草 |" in out
    assert out.count("\n") >= 2


def test_wrap_preserves_bullet_block() -> None:
    raw = "· 牛牛长草：说明一\n· 牛牛作战：说明二"
    out = _wrap_paragraphs_for_help_page(raw)
    assert "· 牛牛长草" in out
    assert "· 牛牛作战" in out


def test_wrap_preserves_numbered_usage_list() -> None:
    raw = (
        "1. 查看好友申请 / 查看入群邀请 — 列出待处理项\n"
        "2. 同意 — 处理最新提醒\n"
        "3. 同意好友 / 拒绝好友 〈QQ号〉 — 按 QQ 审批好友"
    )
    assert _is_numbered_list_block(raw)
    out = _wrap_paragraphs_for_help_page(raw)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) >= 3
    assert lines[0].startswith("1.")
    assert any(ln.startswith("2.") for ln in lines)
    assert any(ln.startswith("3.") for ln in lines)


def test_level1_guide_before_plugin_table() -> None:
    text = generate_plugins_markdown(None)
    guide_pos = text.find("详情")
    table_pos = text.find("## 插件列表")
    assert guide_pos != -1
    assert table_pos != -1
    assert guide_pos < table_pos
    assert "牛牛帮助 1 2" in text
    assert HELP_STATUS_ON in text
    assert HELP_STATUS_OFF in text
    assert "超管·启停范围" not in text


def test_superuser_help_includes_scope_toggle_guide() -> None:
    text = generate_plugins_markdown(None, show_ignored=True)
    assert "牛牛帮助（超级用户）" in text
    assert "超管·启停范围" in text
    assert "牛牛开启 MAA远控" in text
    assert "牛牛关闭 MAA远控 123456789" in text
    assert "global" in text
    assert "群白名单" in text
    assert "全实例禁用" in text


def test_help_list_status_marks() -> None:
    assert help_list_status_mark(True) == HELP_STATUS_ON
    assert help_list_status_mark(False) == HELP_STATUS_OFF


def test_plugin_page_status_banner() -> None:
    enabled = _plugin_page_status_banner("MAA远控", True)
    assert "（" not in enabled
    assert "**状态** 已启用" in enabled
    assert "**牛牛关闭 MAA远控**" in enabled

    disabled = _plugin_page_status_banner("MAA远控", False)
    assert "**状态** 已停用" in disabled
    assert "**牛牛开启 MAA远控**" in disabled


def test_generate_plugins_markdown_reuses_filtered_plugins(monkeypatch) -> None:
    called = False

    def fail_get_help_menu_plugins(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("should reuse filtered_plugins")

    plugin = type(
        "P",
        (),
        {
            "name": "demo",
            "metadata": type("Meta", (), {"name": "示例插件", "description": "desc"})(),
        },
    )()

    monkeypatch.setattr(
        "packages.help.markdown_generator.get_help_menu_plugins",
        fail_get_help_menu_plugins,
    )

    text = generate_plugins_markdown(None, filtered_plugins=[plugin])

    assert "示例插件" in text
    assert called is False
