from src.plugins.request_handler.texts import REQUEST_HANDLER_USAGE_LINES


def test_request_handler_usage_lines_are_grouped_by_task() -> None:
    assert REQUEST_HANDLER_USAGE_LINES == (
        "查看好友申请 / 查看入群申请 — 查看当前待处理申请",
        "同意 / 拒绝 — 处理最新提醒，或引用某条提醒后只处理该条",
        "同意好友 / 拒绝好友 〈QQ号〉；同意入群 / 拒绝入群 〈群号〉 — 按号码处理单条申请",
        "同意所有好友 / 拒绝所有好友；同意所有入群 / 拒绝所有入群 — 批量处理当前列表",
        "查看自动同意；开启 / 关闭自动同意好友；开启 / 关闭自动同意入群 — 查看或切换自动同意",
    )
