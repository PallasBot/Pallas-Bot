from pallas.core.shared.utils.http_msg import (
    PALLAS_VAGUE_REPLY,
    upstream_error_visible_to_user,
    user_failure_reply,
)


def test_user_failure_reply_hides_quota() -> None:
    body = (
        '{"error":{"message":"预扣费额度失败, 用户[17797]剩余额度: $0.017178, '
        '需要预扣费额度: $0.040000 (request id: abc)","code":"insufficient_user_quota"}}'
    )
    assert user_failure_reply(body) == PALLAS_VAGUE_REPLY
    assert not upstream_error_visible_to_user(body)


def test_user_failure_reply_shows_policy_violation_by_code() -> None:
    body = '{"error":{"message":"Your request was rejected.","code":"content_policy_violation"}}'
    assert user_failure_reply(body) == "Your request was rejected."
    assert upstream_error_visible_to_user(body)


def test_user_failure_reply_shows_violation_by_message_zh() -> None:
    body = '{"error":{"message":"生成失败：提示词包含敏感信息，未通过内容审核"}}'
    reply = user_failure_reply(body)
    assert reply == "生成失败：提示词包含敏感信息，未通过内容审核"
    assert upstream_error_visible_to_user(body)


def test_user_failure_reply_strips_request_id() -> None:
    body = '{"error":{"message":"内容违规，请修改后重试 (request id: xyz123)","code":"moderation_blocked"}}'
    assert user_failure_reply(body) == "内容违规，请修改后重试"


def test_user_failure_reply_unclassified_is_vague() -> None:
    body = '{"error":{"message":"unknown gateway fault 502"}}'
    assert user_failure_reply(body) == PALLAS_VAGUE_REPLY
