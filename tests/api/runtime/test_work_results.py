from __future__ import annotations

import pytest

from pallas.api.runtime import DirectBotAction, DirectWorkResult


def test_direct_bot_action_normalizes_and_copies_public_payload() -> None:
    payload = {"group_id": 42, "message_text": "hello", "metadata": {"source": "test"}}

    action = DirectBotAction(
        action=" send_group_msg ",
        target_bot_id=123,
        payload=payload,
        timeout_sec=12,
    )
    payload["metadata"]["source"] = "changed"

    assert action.action == "send_group_msg"
    assert action.target_bot_id == 123
    assert action.payload == {"group_id": 42, "message_text": "hello", "metadata": {"source": "test"}}
    assert action.timeout_sec == 12
    assert DirectWorkResult(actions=(action,)).actions == (action,)


def test_direct_work_result_freezes_the_action_collection() -> None:
    actions = [DirectBotAction("send_group_msg", 123, {"group_id": 42, "message_text": "hello"})]

    result = DirectWorkResult(actions=actions)
    actions.clear()

    assert result.actions == (DirectBotAction("send_group_msg", 123, {"group_id": 42, "message_text": "hello"}),)


def test_direct_work_result_rejects_unknown_action_values() -> None:
    with pytest.raises(ValueError, match="actions must contain DirectBotAction values"):
        DirectWorkResult(actions=(object(),))


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"action": " ", "target_bot_id": 1, "payload": {}}, "action is required"),
        ({"action": "send_group_msg", "target_bot_id": 0, "payload": {}}, "target bot is required"),
        ({"action": "send_group_msg", "target_bot_id": 1, "payload": []}, "payload must be a dict"),
        (
            {"action": "send_group_msg", "target_bot_id": 1, "payload": {}, "timeout_sec": 0},
            "timeout must be positive",
        ),
        (
            {"action": "onebot_call_api", "target_bot_id": 1, "payload": {"api": "set_group_ban"}},
            "unsupported action",
        ),
        (
            {"action": "send_group_msg", "target_bot_id": 1, "payload": {"message_text": "hello"}},
            "group_id must be positive",
        ),
        (
            {"action": "send_private_msg", "target_bot_id": 1, "payload": {"user_id": 7}},
            "message payload is required",
        ),
    ],
)
def test_direct_bot_action_rejects_invalid_values(values: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DirectBotAction(**values)
