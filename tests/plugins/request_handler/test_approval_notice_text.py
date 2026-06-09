from src.plugins.request_handler.approval_notice_text import parse_approval_notice_meta


def test_parse_friend_approval_notice_meta() -> None:
    text = "[好友申请]\n申请人：测试（123456）\n验证：-\n帮助：牛牛帮助 申请管理"
    assert parse_approval_notice_meta(text) == {"kind": "friend", "target_id": "123456"}


def test_parse_group_approval_notice_meta() -> None:
    text = "[入群邀请]\n邀请人：测试（654321）\n群：示例群（793721499）\n帮助：牛牛帮助 申请管理"
    assert parse_approval_notice_meta(text) == {"kind": "group", "target_id": "793721499"}


def test_parse_approval_notice_meta_rejects_non_notice_text() -> None:
    assert parse_approval_notice_meta("普通聊天消息") is None
