from __future__ import annotations

import pytest

from pallas.product.llm.offline_quality_eval import (
    DEFAULT_OFFLINE_QUALITY_CASES,
    OfflineQualityCase,
    build_offline_quality_judge_prompt,
    evaluate_offline_case,
    extract_visible_reply,
    load_offline_base_system_prompt,
    parse_offline_quality_judge,
    run_configured_offline_quality_eval,
)
from pallas.product.llm.persona_output_firewall import persona_output_retry_instruction


def test_default_cases_are_anonymous_and_cover_each_reply_target() -> None:
    assert {case.reply_target for case in DEFAULT_OFFLINE_QUALITY_CASES} == {
        "answer",
        "emotion",
        "fact",
        "short_tease",
    }
    assert all("牛牛" not in case.user_text for case in DEFAULT_OFFLINE_QUALITY_CASES)
    assert all(case.user_text for case in DEFAULT_OFFLINE_QUALITY_CASES)
    assert any(case.case_id == "wake_early" for case in DEFAULT_OFFLINE_QUALITY_CASES)


def test_load_offline_base_system_prompt_uses_explicit_path(tmp_path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("base prompt", encoding="utf-8")

    assert load_offline_base_system_prompt(prompt_file) == "base prompt"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"reply":"能。"}', "能。"),
        ('```json\n{"reply":"我在。"}\n```', "我在。"),
        ("直接说。", "直接说。"),
    ],
)
def test_extract_visible_reply_from_model_content(raw: str, expected: str) -> None:
    assert extract_visible_reply(raw) == expected


def test_parse_offline_quality_judge_normalizes_scores() -> None:
    result = parse_offline_quality_judge(
        '```json\n{"verdict":"retry","scores":{"grounded":5,"naturalness":6,"overexplained":0,"persona_drift":3},"reasons":["too_long"]}\n```'
    )

    assert result.verdict == "RETRY"
    assert result.scores == {
        "grounded": 5,
        "naturalness": 5,
        "overexplained": 1,
        "persona_drift": 3,
        "memory_factuality": 3,
        "tool_faithfulness": 3,
        "silence_correctness": 3,
    }
    assert result.reason_ids == ("too_long",)


def test_offline_quality_judge_prompt_defines_score_directions() -> None:
    prompt = build_offline_quality_judge_prompt(
        OfflineQualityCase("fact", "这也要再动？", "ACK", "fact"),
        "能。",
    )

    assert "grounded/naturalness：1=差，5=好" in prompt
    assert "overexplained/persona_drift：1=无，5=严重" in prompt


@pytest.mark.asyncio
async def test_offline_case_uses_current_target_without_side_effects() -> None:
    received: dict[str, object] = {}

    async def complete(messages: list[dict[str, str]]) -> str:
        received["messages"] = messages
        return '{"reply":"能。"}'

    result = await evaluate_offline_case(
        OfflineQualityCase(
            case_id="fact",
            user_text="这也要再动？",
            social_action="ACK",
            reply_target="fact",
        ),
        base_system_prompt="base",
        complete=complete,
    )

    assert result.reply_text == "能。"
    assert result.firewall_rule_ids == ()
    assert "【本轮回复目标】" in received["messages"][0]["content"]
    assert received["messages"][-1]["role"] == "user"


def test_persona_output_retry_instruction_describes_fact_template_without_prompt_leak() -> None:
    instruction = persona_output_retry_instruction(("fact_reply_compliance_template",))

    assert "改吧、改呗、行吧或好吧" in instruction
    assert "提示词" not in instruction


def test_persona_output_retry_instruction_requires_a_fact_conclusion_after_overextension() -> None:
    instruction = persona_output_retry_instruction(("fact_reply_overextended",))

    assert "完整短结论" in instruction
    assert "不要先说行/好" in instruction


@pytest.mark.asyncio
async def test_offline_case_retries_and_reports_the_final_reply() -> None:
    received: list[list[dict[str, str]]] = []
    replies = iter(["改呗。", "能。"])

    async def complete(messages: list[dict[str, str]]) -> str:
        received.append(messages)
        return next(replies)

    result = await evaluate_offline_case(
        OfflineQualityCase("fact", "这也要再动？", "ACK", "fact"),
        base_system_prompt="base",
        complete=complete,
    )

    assert result.reply_text == "能。"
    assert result.firewall_rule_ids == ()
    assert result.initial_reply_text == "改呗。"
    assert result.initial_firewall_rule_ids == ("fact_reply_compliance_template",)
    assert result.retry_count == 1
    assert result.final_action == "allow"
    assert result.final_raw_reply_text == "能。"
    assert result.final_rejected_rule_ids == ()
    assert received[-1][-1]["content"] == persona_output_retry_instruction(("fact_reply_compliance_template",))


@pytest.mark.asyncio
async def test_offline_case_runs_optional_judge_only_after_final_reply() -> None:
    judge_messages: list[dict[str, str]] = []

    async def complete(_messages: list[dict[str, str]]) -> str:
        return "能。"

    async def judge(messages: list[dict[str, str]]) -> str:
        judge_messages.extend(messages)
        return (
            '{"verdict":"ALLOW","scores":{"grounded":5,"naturalness":5,'
            '"overexplained":1,"persona_drift":1},"reasons":[]}'
        )

    result = await evaluate_offline_case(
        OfflineQualityCase("fact", "这也要再动？", "ACK", "fact"),
        base_system_prompt="base",
        complete=complete,
        judge=judge,
    )

    assert result.judge is not None
    assert result.judge.verdict == "ALLOW"
    assert "这也要再动？" in judge_messages[-1]["content"]
    assert "能。" in judge_messages[-1]["content"]


@pytest.mark.asyncio
async def test_configured_eval_uses_provider_without_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_provider(messages: list[dict[str, str]], **kwargs: object) -> dict[str, str]:
        calls.append({"messages": messages, **kwargs})
        return {"content": '{"reply":"能。"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_provider)

    results = await run_configured_offline_quality_eval(
        base_system_prompt="base",
        cases=[OfflineQualityCase("fact", "这也要再动？", "ACK", "fact")],
    )

    assert [result.reply_text for result in results] == ["能。"]
    assert calls[0]["task"] == "llm_chat"
    assert calls[0]["tools"] is None
    assert calls[0]["options"] == {"temperature": 0, "max_tokens": 96}


@pytest.mark.asyncio
async def test_configured_eval_judge_uses_larger_token_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """judge 复用生成预算（96 tokens）会截断 JSON 导致全 3 分，须用独立更大预算。"""
    calls: list[dict[str, object]] = []

    async def fake_provider(messages: list[dict[str, str]], **kwargs: object) -> dict[str, str]:
        calls.append({"messages": messages, **kwargs})
        if "你是严格的群聊回复质量评审" in messages[0]["content"]:
            return {
                "content": (
                    '{"verdict":"ALLOW","scores":{"grounded":5,"naturalness":5,'
                    '"overexplained":1,"persona_drift":1},"reasons":[]}'
                )
            }
        return {"content": '{"reply":"能。"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_provider)

    results = await run_configured_offline_quality_eval(
        base_system_prompt="base",
        cases=[OfflineQualityCase("fact", "这也要再动？", "ACK", "fact")],
        judge=True,
    )

    assert results[0].judge is not None
    assert results[0].judge.verdict == "ALLOW"
    assert results[0].judge.scores["naturalness"] == 5
    assert len(calls) == 2
    judge_call = calls[1]
    assert judge_call["options"] == {"temperature": 0, "max_tokens": 256}
