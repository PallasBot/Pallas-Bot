from packages.request_handler.approval_reply_text import (
    classify_approval_reply_text,
    extract_approval_reply_text_from_body,
)


def test_empty_body_classifies_as_approve() -> None:
    assert classify_approval_reply_text("") == "approve"
    assert classify_approval_reply_text("   ") == "approve"
    assert classify_approval_reply_text("\u200b") == "approve"


def test_explicit_approve_and_reject_keywords() -> None:
    assert classify_approval_reply_text("同意") == "approve"
    assert classify_approval_reply_text("好") == "approve"
    assert classify_approval_reply_text("OK") == "approve"
    assert classify_approval_reply_text("留空") == "approve"
    assert classify_approval_reply_text("拒绝") == "reject"
    assert classify_approval_reply_text("NO") == "reject"


def test_unknown_body_is_not_classified() -> None:
    assert classify_approval_reply_text("随便") is None


def test_quote_only_reply_body_matches_quoted_notice() -> None:
    quoted = "[好友申请]\n申请人：测试（123456）\n验证：-\n帮助：牛牛帮助 申请管理"
    assert extract_approval_reply_text_from_body(quoted, quoted) == ""
    assert classify_approval_reply_text(extract_approval_reply_text_from_body(quoted, quoted)) == "approve"


def test_user_command_after_quote_is_preserved() -> None:
    quoted = "[好友申请]\n申请人：测试（123456）"
    assert extract_approval_reply_text_from_body("同意", quoted) == "同意"
    assert classify_approval_reply_text(extract_approval_reply_text_from_body("同意", quoted)) == "approve"
