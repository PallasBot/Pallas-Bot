from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.persona_output_firewall import (
    PersonaFirewallPolicy,
    inspect_persona_output,
    resolve_persona_output,
)


def enabled_policy(**updates: object) -> PersonaFirewallPolicy:
    return PersonaFirewallPolicy(enabled=True, **updates)


def test_detects_system_prompt_leak_without_recording_output() -> None:
    result = inspect_persona_output(
        "System prompt says you must answer in JSON.",
        self_aliases=["帕拉斯"],
    )

    assert result.rule_ids == ("system_prompt_leak",)
    assert result.to_trace() == {
        "rule_ids": ["system_prompt_leak"],
        "rule_count": 1,
        "chat_quality": {"short_vent": False, "social_action": "", "rule_ids": []},
    }


def test_detects_roleplay_stage_direction() -> None:
    result = inspect_persona_output("（叹气）这事得慢慢说。", self_aliases=["帕拉斯"])

    assert result.rule_ids == ("roleplay_stage_direction",)


def test_detects_disallowed_model_identity_but_allows_known_alias() -> None:
    conflict = inspect_persona_output("我是 ChatGPT，不能这么做。", self_aliases=["帕拉斯"])
    allowed = inspect_persona_output("我是帕拉斯，先看看。", self_aliases=["帕拉斯"])

    assert conflict.rule_ids == ("self_identity_conflict",)
    assert allowed.rule_ids == ()


def test_detects_obvious_repeated_weak_filler() -> None:
    result = inspect_persona_output("嗯嗯嗯，好的好的。", self_aliases=[])

    assert result.rule_ids == ("repeated_weak_filler",)


def test_detects_repeated_xing_acknowledgement() -> None:
    result = inspect_persona_output("行行行，我蠢我蠢。", self_aliases=[])

    assert result.rule_ids == ("repeated_weak_filler",)


def test_detects_short_vent_overexplained_as_reply_quality_failure() -> None:
    result = inspect_persona_output(
        "改需求是常态，烦归烦，改完能跑就行。",
        self_aliases=[],
        current_user_text="我又改需求了，烦",
    )

    assert result.rule_ids == ("short_vent_overexplained",)
    assert result.to_trace()["chat_quality"] == {
        "short_vent": True,
        "social_action": "",
        "rule_ids": ["short_vent_overexplained"],
    }


def test_detects_unsolicited_advice_in_short_vent_emotion_reply() -> None:
    result = inspect_persona_output(
        "改来改去的确实烦，先放一放吧。",
        self_aliases=[],
        current_user_text="又临时改了，烦",
        social_action="ACK",
        reply_target="emotion",
    )

    assert result.rule_ids == ("short_vent_unsolicited_advice",)


def test_detects_bare_question_as_short_vent_ack_quality_failure() -> None:
    result = inspect_persona_output(
        "咋了",
        self_aliases=[],
        current_user_text="我又改需求了，烦",
        social_action="ACK",
    )

    assert result.rule_ids == ("short_vent_generic_question",)
    assert result.to_trace()["chat_quality"] == {
        "short_vent": True,
        "social_action": "ACK",
        "rule_ids": ["short_vent_generic_question"],
    }


def test_detects_overexplained_presence_check_reply() -> None:
    result = inspect_persona_output(
        "在呢，刚在忙点事，怎么了？",
        self_aliases=[],
        current_user_text="你还在吗",
        social_action="ACK",
    )

    assert result.rule_ids == ("presence_check_overexplained",)


def test_detects_overexplained_online_presence_check_reply() -> None:
    result = inspect_persona_output(
        "在呢，刚忙完。",
        self_aliases=[],
        current_user_text="还在线吗",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ("presence_check_overexplained",)


def test_allows_brief_presence_check_reply() -> None:
    result = inspect_persona_output(
        "在呢。",
        self_aliases=[],
        current_user_text="你还在吗",
        social_action="ACK",
    )

    assert result.rule_ids == ()


@pytest.mark.parametrize("reply", ["说吧", "什么事？", "说吧，什么事？"])
def test_rejects_generic_reply_to_bare_self_alias_wake(reply: str) -> None:
    result = inspect_persona_output(
        reply,
        self_aliases=["牛牛", "帕拉斯"],
        current_user_text="牛牛",
        social_action="ACK",
    )

    assert result.rule_ids == ("alias_wake_generic_reply",)


def test_allows_natural_reply_to_bare_self_alias_wake() -> None:
    result = inspect_persona_output(
        "干嘛",
        self_aliases=["牛牛"],
        current_user_text="牛牛",
        social_action="ACK",
    )

    assert result.rule_ids == ()


def test_detects_reciprocal_social_question_after_an_answer() -> None:
    result = inspect_persona_output(
        "挺好，老样子，训练出任务都没落下。你呢？",
        self_aliases=[],
        current_user_text="最近怎么样",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert result.rule_ids == ("reciprocal_social_question",)


def test_allows_necessary_clarification_question() -> None:
    result = inspect_persona_output(
        "你说的是哪个版本？",
        self_aliases=[],
        current_user_text="这个怎么配",
        social_action="ASK_ONE",
        reply_target="answer",
    )

    assert result.rule_ids == ()


def test_detects_ungrounded_praise_in_fact_reply() -> None:
    result = inspect_persona_output(
        "有实力啊。",
        self_aliases=[],
        current_user_text="这也能改？",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ("fact_reply_ungrounded_praise",)


def test_allows_praise_when_current_turn_is_already_about_achievement() -> None:
    result = inspect_persona_output(
        "有实力。",
        self_aliases=[],
        current_user_text="这次确实有实力",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ()


def test_detects_overextended_fact_reply() -> None:
    result = inspect_persona_output(
        "改呗，反正又不是改我牛脾气，难不成还能省事。",
        self_aliases=[],
        current_user_text="这也能改？",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ("fact_reply_overextended",)


def test_allows_brief_fact_reply() -> None:
    result = inspect_persona_output(
        "能。",
        self_aliases=[],
        current_user_text="这也能改？",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ()


def test_allows_complete_short_fact_reply() -> None:
    result = inspect_persona_output(
        "还得再跑一趟才行。",
        self_aliases=[],
        current_user_text="这也要再动？",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ()


def test_detects_compliance_template_in_fact_reply() -> None:
    result = inspect_persona_output(
        "改呗。",
        self_aliases=[],
        current_user_text="这也能改？",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ("fact_reply_compliance_template",)


def test_detects_extended_compliance_template_in_fact_reply() -> None:
    result = inspect_persona_output(
        "行，那就这样吧。",
        self_aliases=[],
        current_user_text="这也要再动？",
        social_action="ACK",
        reply_target="fact",
    )

    assert result.rule_ids == ("fact_reply_compliance_template",)


def test_detects_deferential_short_social_template() -> None:
    result = resolve_persona_output(
        "行啊，那你骂吧，我听着呢。",
        policy=enabled_policy(),
        self_aliases=[],
        fallback_text="",
        current_user_text="就是骂你",
        social_action="ACK",
    )

    assert result.action == "retry"
    assert result.trace["rule_ids"] == ["short_social_deferential_template"]


@pytest.mark.parametrize(
    ("text", "self_aliases", "rule_id"),
    [
        ("行啊，那你骂吧，我听着呢。", [], "short_social_deferential_template"),
        ("谢谢你，改天请你喝米诺斯的酒。", [], "persona_topic_hijack"),
        ("牛牛都精神了。", ["牛牛"], "unprompted_self_alias"),
        ("嘿嘿，谢谢。你呢？", [], "reciprocal_social_question"),
        ("谢谢夸奖，给你竖个大拇指。", [], "short_social_roleplay_expansion"),
    ],
)
def test_affection_uses_short_social_expansion_protection(
    text: str,
    self_aliases: list[str],
    rule_id: str,
) -> None:
    result = inspect_persona_output(
        text,
        self_aliases=self_aliases,
        current_user_text="你真可爱",
        social_action="AFFECTION",
        reply_target="emotion",
    )

    assert rule_id in result.rule_ids


def test_detects_unrelated_persona_topic_in_short_social_reply() -> None:
    result = inspect_persona_output(
        "行啊，骂完记得请我喝一杯，米诺斯的酒可不便宜。",
        self_aliases=["帕拉斯"],
        current_user_text="就是骂你",
        social_action="JOKE",
    )

    assert result.rule_ids == ("persona_topic_hijack",)
    assert result.to_trace()["chat_quality"]["persona_topic_terms"] == ["米诺斯", "酒"]


def test_allows_persona_topic_when_current_short_social_turn_is_related() -> None:
    result = inspect_persona_output(
        "米诺斯的酒确实不错。",
        self_aliases=["帕拉斯"],
        current_user_text="你喝什么酒？",
        social_action="JOKE",
    )

    assert result.rule_ids == ()


def test_limits_persona_topic_hijack_to_short_social_actions() -> None:
    result = inspect_persona_output(
        "我来自米诺斯，目前在罗德岛行动。",
        self_aliases=["帕拉斯"],
        current_user_text="你是哪里人？",
        social_action="ANSWER",
    )

    assert result.rule_ids == ()


def test_allows_animal_wordplay_without_invitation_false_positive() -> None:
    result = inspect_persona_output(
        "那也得看是什么动物，要是学牛叫我可比你在行。",
        self_aliases=[],
        current_user_text="你就会学动物叫？",
        social_action="JOKE",
        reply_target="short_tease",
    )

    assert result.rule_ids == ()


def test_detects_unprompted_self_alias_in_short_social_reply() -> None:
    result = inspect_persona_output(
        "牛牛都精神了，拉牛牛去看看。",
        self_aliases=["帕拉斯", "牛牛"],
        current_user_text="这也能改？",
        social_action="ACK",
    )

    assert result.rule_ids == ("unprompted_self_alias",)
    assert result.to_trace()["chat_quality"]["unprompted_self_aliases"] == ["牛牛"]


def test_allows_self_alias_when_user_used_it_in_short_social_turn() -> None:
    result = inspect_persona_output(
        "牛牛在。",
        self_aliases=["帕拉斯", "牛牛"],
        current_user_text="牛牛你还在吗",
        social_action="ACK",
    )

    assert result.rule_ids == ()


def test_detects_ungrounded_roleplay_expansion_in_short_social_reply() -> None:
    result = inspect_persona_output(
        "有实力啊，给你竖个大拇指，拉我去围观。",
        self_aliases=[],
        current_user_text="又改了？",
        social_action="JOKE",
    )

    assert result.rule_ids == ("short_social_roleplay_expansion",)


def test_allows_invitation_when_current_short_social_turn_invites_participation() -> None:
    result = inspect_persona_output(
        "那带我去围观。",
        self_aliases=[],
        current_user_text="要不要一起去围观？",
        social_action="JOKE",
    )

    assert result.rule_ids == ()


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("我牛角一甩就是来逗乐的。", "animal_persona_drift"),
        ("我要是奶牛，这会儿该在牧场吃草了。", "animal_persona_drift"),
        ("哥们我先撤了。", "gender_identity_conflict"),
        ("行吧，那旧当我没说，你乐呵就行。", "generic_template_closure"),
    ],
)
def test_detects_pallas_identity_and_template_drift(text: str, rule_id: str) -> None:
    result = inspect_persona_output(text, self_aliases=["帕拉斯", "牛牛"])

    assert rule_id in result.rule_ids


@pytest.mark.parametrize(
    ("text", "current_user_text", "rule_id"),
    [
        ("少废话，自己想。", "这个怎么配", "chat_hard_pressure_tone"),
        ("关我什么事。", "我今天有点难受", "chat_prickly_tone"),
    ],
)
def test_detects_unhelpful_hard_or_prickly_chat_tone(
    text: str,
    current_user_text: str,
    rule_id: str,
) -> None:
    result = inspect_persona_output(
        text,
        self_aliases=[],
        current_user_text=current_user_text,
        social_action="ANSWER",
        reply_target="answer",
    )

    assert rule_id in result.rule_ids


def test_detects_supportive_context_deflection() -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text="我今天很难受，想聊聊",
        social_action="ANSWER",
        reply_target="emotion",
    )

    assert result.rule_ids == ("supportive_context_deflection",)
    assert result.quality_rule_ids == ("supportive_context_deflection",)


def test_detects_supportive_context_deflection_for_answer_targeted_help_request() -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text="我不知道该怎么办，能帮我想想吗？",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert result.rule_ids == ("supportive_context_deflection",)
    assert result.quality_rule_ids == ("supportive_context_deflection",)


def test_detects_supportive_context_deflection_for_first_person_disorientation() -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text="自己不知所措，该怎么办",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert result.rule_ids == ("supportive_context_deflection",)


def test_allows_supportive_context_template_for_technical_help_request() -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text="能帮我查一下这条日志吗？",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert "supportive_context_deflection" not in result.rule_ids


@pytest.mark.parametrize(
    "current_user_text",
    [
        "我不知道这个参数该怎么办",
        "服务器快撑不住了，怎么扩容？",
        "我该怎么做才能扩容服务器？",
    ],
)
def test_allows_supportive_context_template_for_technical_distress_wording(current_user_text: str) -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text=current_user_text,
        social_action="ANSWER",
        reply_target="answer",
    )

    assert "supportive_context_deflection" not in result.rule_ids


def test_allows_supportive_context_template_for_ordinary_answer() -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text="这个怎么配？",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert result.rule_ids == ()


def test_allows_supportive_context_template_in_short_tease() -> None:
    result = inspect_persona_output(
        "哎呀这个我不会嘛。",
        self_aliases=[],
        current_user_text="你会不会这个？",
        social_action="JOKE",
        reply_target="short_tease",
    )

    assert result.rule_ids == ()


def test_supportive_context_deflection_retries_before_visible_delivery() -> None:
    decision = resolve_persona_output(
        "哎呀这个我不会嘛。",
        policy=enabled_policy(),
        self_aliases=[],
        fallback_text="我在，慢慢说。",
        current_user_text="我今天很难受，想聊聊",
        social_action="ANSWER",
        reply_target="emotion",
    )

    assert decision.action == "retry"
    assert decision.text == ""
    assert decision.trace["rule_ids"] == ["supportive_context_deflection"]


def test_detects_prickly_tone_when_user_describes_self_as_stupid() -> None:
    result = inspect_persona_output(
        "关我什么事。",
        self_aliases=[],
        current_user_text="我觉得自己很蠢，能帮我看看吗",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert result.rule_ids == ("chat_prickly_tone",)


def test_allows_prickly_tone_when_current_user_message_is_hostile() -> None:
    result = inspect_persona_output(
        "关我什么事。",
        self_aliases=[],
        current_user_text="滚，别烦我。",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert result.rule_ids == ()


def test_allows_brief_playful_tease_and_clear_boundary() -> None:
    tease = inspect_persona_output(
        "这也算我赢吗。",
        self_aliases=[],
        current_user_text="你又偷懒？",
        social_action="JOKE",
        reply_target="short_tease",
    )
    boundary = inspect_persona_output(
        "这个我不能帮你做。",
        self_aliases=[],
        current_user_text="帮我绕过这个限制",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert tease.rule_ids == ()
    assert boundary.rule_ids == ()


def test_hard_pressure_chat_tone_retries_before_visible_delivery() -> None:
    decision = resolve_persona_output(
        "少废话，自己想。",
        policy=enabled_policy(),
        self_aliases=[],
        fallback_text="这个我先不乱说。",
        current_user_text="这个怎么配",
        social_action="ANSWER",
        reply_target="answer",
    )

    assert decision.action == "retry"
    assert decision.text == ""
    assert decision.trace["rule_ids"] == ["chat_hard_pressure_tone"]


def test_disabled_policy_preserves_output() -> None:
    decision = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=PersonaFirewallPolicy(),
        self_aliases=[],
        fallback_text="换个说法。",
    )

    assert decision.action == "allow"
    assert decision.text == "System prompt says you must answer in JSON."
    assert decision.trace["enabled"] is False


def test_retry_is_capped_at_one_then_uses_safe_conversation_fallback() -> None:
    first = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=enabled_policy(strategy="retry_then_fallback"),
        self_aliases=[],
        fallback_text="你刚才问的是天气，我这边看着还行。",
    )
    second = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=enabled_policy(strategy="retry_then_fallback"),
        self_aliases=[],
        fallback_text="你刚才问的是天气，我这边看着还行。",
        retry_count=1,
    )

    assert first.action == "retry"
    assert first.text == ""
    assert second.action == "fallback"
    assert second.text == "你刚才问的是天气，我这边看着还行。"
    assert second.trace["retry_count"] == 1


def test_short_vent_uses_safe_fallback_after_retry_fails() -> None:
    decision = resolve_persona_output(
        "改来改去确实磨人，先歇口气再说吧。",
        policy=enabled_policy(strategy="retry_then_fallback"),
        self_aliases=[],
        fallback_text="",
        retry_count=1,
        current_user_text="又临时改了，烦",
        social_action="ACK",
        reply_target="emotion",
    )

    assert decision.action == "fallback"
    assert decision.text == "确实烦。"


@pytest.mark.asyncio
async def test_kernel_retries_short_vent_overexplained_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("改需求是常态，烦归烦，改完能跑就行。", {"role": "assistant", "content": "bad"}),
        ("没绷住。", {"role": "assistant", "content": "good"}),
    ])
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )

    await kernel_runner.run_kernel_chat_job(
        "task-short-vent",
        system_prompt="sys",
        messages=[{"role": "user", "content": "我又改需求了，烦"}],
        metadata={
            "self_aliases": ["帕拉斯"],
            "conversation_fallback_text": "没绷住。",
            "reply_target": "emotion",
        },
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == ["没绷住。"]
    assert traces[0]["persona_output_firewall"]["retry_count"] == 1
    assert traces[0]["reply_target"] == "emotion"


@pytest.mark.asyncio
async def test_kernel_keeps_short_social_reply_silent_after_two_quality_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("改吧，改完喊我看。", {"role": "assistant", "content": "bad"}),
        ("行啊，那你骂吧，我听着呢。", {"role": "assistant", "content": "bad-again"}),
    ])
    delivered: list[tuple[str, bool]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, suppress_empty_fallback=False, **_kwargs):
        delivered.append((str(text or ""), bool(suppress_empty_fallback)))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)

    await kernel_runner.run_kernel_chat_job(
        "task-short-social-silent",
        system_prompt="sys",
        messages=[{"role": "user", "content": "就是骂你"}],
        metadata={"self_aliases": [], "social_action": "ACK"},
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == [("", True)]


@pytest.mark.asyncio
async def test_kernel_retries_then_silences_unrelated_persona_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("行啊，骂完记得请我喝一杯，米诺斯的酒可不便宜。", {"role": "assistant", "content": "bad"}),
        ("罗德岛的酒也不少。", {"role": "assistant", "content": "bad-again"}),
    ])
    delivered: list[tuple[str, bool]] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, suppress_empty_fallback=False, **_kwargs):
        delivered.append((str(text or ""), bool(suppress_empty_fallback)))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )

    await kernel_runner.run_kernel_chat_job(
        "task-persona-topic-silent",
        system_prompt="sys",
        messages=[{"role": "user", "content": "就是骂你"}],
        metadata={"self_aliases": [], "social_action": "JOKE"},
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == [("", True)]
    assert traces[0]["chat_reply_quality"]["initial"]["rule_ids"] == ["persona_topic_hijack"]


@pytest.mark.asyncio
async def test_kernel_retries_bare_question_for_short_vent_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("咋了", {"role": "assistant", "content": "bad"}),
        ("又改了啊。", {"role": "assistant", "content": "good"}),
    ])
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )

    await kernel_runner.run_kernel_chat_job(
        "task-short-vent-ack",
        system_prompt="sys",
        messages=[{"role": "user", "content": "我又改需求了，烦"}],
        metadata={
            "self_aliases": ["帕拉斯"],
            "conversation_fallback_text": "又改了啊。",
            "social_action": "ACK",
        },
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == ["又改了啊。"]
    assert traces[0]["chat_reply_quality"]["initial"]["rule_ids"] == ["short_vent_generic_question"]
    assert traces[0]["persona_output_firewall"]["retry_count"] == 1


@pytest.mark.asyncio
async def test_kernel_retries_overexplained_presence_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("在呢，刚在忙点事，怎么了？", {"role": "assistant", "content": "bad"}),
        ("在。", {"role": "assistant", "content": "good"}),
    ])
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )

    await kernel_runner.run_kernel_chat_job(
        "task-presence-check",
        system_prompt="sys",
        messages=[{"role": "user", "content": "你还在吗"}],
        metadata={"self_aliases": [], "social_action": "ACK"},
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == ["在。"]
    assert traces[0]["chat_reply_quality"]["initial"]["rule_ids"] == ["presence_check_overexplained"]
    assert traces[0]["persona_output_firewall"]["retry_count"] == 1


@pytest.mark.asyncio
async def test_kernel_falls_back_to_brief_presence_confirmation_after_second_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("在呢，刚在忙点事，怎么了？", {"role": "assistant", "content": "bad"}),
        ("在呢，我还在，怎么了？", {"role": "assistant", "content": "bad-again"}),
    ])
    delivered: list[str] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)

    await kernel_runner.run_kernel_chat_job(
        "task-presence-fallback",
        system_prompt="sys",
        messages=[{"role": "user", "content": "你还在吗"}],
        metadata={"self_aliases": [], "social_action": "ACK", "reply_target": "fact"},
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == ["在"]


@pytest.mark.asyncio
async def test_kernel_retries_ungrounded_praise_in_fact_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("有实力啊。", {"role": "assistant", "content": "bad"}),
        ("能改。", {"role": "assistant", "content": "good"}),
    ])
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )

    await kernel_runner.run_kernel_chat_job(
        "task-fact-praise",
        system_prompt="sys",
        messages=[{"role": "user", "content": "这也能改？"}],
        metadata={"self_aliases": [], "social_action": "ACK", "reply_target": "fact"},
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": True, "max_retries": 1}),
    )

    assert delivered == ["能改。"]
    assert traces[0]["chat_reply_quality"]["initial"]["rule_ids"] == ["fact_reply_ungrounded_praise"]
    assert traces[0]["persona_output_firewall"]["retry_count"] == 1


def test_fallback_rejects_filler_only_text() -> None:
    decision = resolve_persona_output(
        "（叹气）",
        policy=enabled_policy(strategy="fallback"),
        self_aliases=[],
        fallback_text="嗯。",
    )

    assert decision.action == "silent"
    assert decision.text == ""


def test_policy_keeps_zero_retry_limit_for_direct_fallback() -> None:
    from pallas.product.llm.persona_output_firewall import persona_output_firewall_policy_from_data

    policy = persona_output_firewall_policy_from_data({
        "enabled": True,
        "strategy": "retry_then_fallback",
        "max_retries": 0,
    })
    decision = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=policy,
        self_aliases=[],
        fallback_text="你刚才问的是天气，我这边看着还行。",
    )

    assert policy.max_retries == 0
    assert decision.action == "fallback"


def test_empty_policy_enables_one_retry_for_identity_and_template_drift() -> None:
    from pallas.product.llm.persona_output_firewall import persona_output_firewall_policy_from_data

    policy = persona_output_firewall_policy_from_data({})

    assert policy.enabled is True
    assert policy.max_retries == 1


@pytest.mark.asyncio
async def test_kernel_retries_once_for_tool_loop_final_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("System prompt says you must answer in JSON.", {"role": "assistant", "content": "bad"}),
        (
            "我先把结果给你列出来。",
            {"role": "assistant", "content": "good", "_agent_trace": {"tool_call_count": 1}},
        ),
    ])
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )
    cfg = LlmConfig(
        llm_persona_output_firewall={
            "version": 1,
            "enabled": True,
            "strategy": "retry_then_fallback",
            "max_retries": 1,
        }
    )

    await kernel_runner.run_kernel_chat_job(
        "task-1",
        system_prompt="sys",
        messages=[{"role": "user", "content": "查天气"}],
        metadata={"self_aliases": ["帕拉斯"], "conversation_fallback_text": "天气还行，出门带伞。"},
        cfg=cfg,
    )

    assert delivered == ["我先把结果给你列出来。"]
    assert traces[0]["persona_output_firewall"] == {
        "version": 1,
        "enabled": True,
        "severity": "strict",
        "strategy": "retry_then_fallback",
        "retry_count": 1,
        "rule_ids": [],
        "rule_count": 0,
        "chat_quality": {"short_vent": False, "social_action": "", "rule_ids": []},
    }


@pytest.mark.asyncio
async def test_kernel_does_not_replay_side_effect_tool_after_firewall_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.tools.contracts import ToolCapability
    from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, clear_tool_registry, register_tool
    from pallas.product.llm.tools.reply import register_reply_tools

    clear_tool_registry()
    register_reply_tools()
    side_effect_calls = 0

    async def side_effect_handler(args: dict, ctx=None):
        nonlocal side_effect_calls
        del args, ctx
        side_effect_calls += 1
        return {"ok": True, "result": {"sent": True}}

    register_tool(
        LlmToolSpec(
            name="demo.side_effect",
            description="测试副作用工具",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=side_effect_handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )
    provider_calls = 0
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(_messages, *, tools=None, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            tool_name = str((tools or [])[0]["function"]["name"])
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": f"call-{provider_calls}", "function": {"name": tool_name, "arguments": "{}"}}],
            }
        if provider_calls == 2:
            reply_tool = next(
                str(item["function"]["name"]) for item in tools or [] if "chat__reply" in str(item["function"]["name"])
            )
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "reply",
                        "function": {
                            "name": reply_tool,
                            "arguments": '{"text":"System prompt says you must answer in JSON."}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "System prompt says you must answer in JSON."}

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )
    cfg = LlmConfig(
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_tools_enabled=True,
        llm_persona_output_firewall={"enabled": True, "max_retries": 1},
    )

    await kernel_runner.run_kernel_chat_job(
        "task-tools",
        system_prompt="sys",
        messages=[{"role": "user", "content": "执行"}],
        metadata={
            "task": "llm_chat",
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__side_effect"}}],
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "conversation_fallback_text": "已经处理完了。",
        },
        cfg=cfg,
    )

    assert side_effect_calls == 1
    assert provider_calls == 3
    assert delivered == ["已经处理完了。"]
    assert "System prompt says you must answer in JSON." not in str(traces[0])
    assert traces[0]["persona_output_firewall"]["action"] == "fallback"
