from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.behavior import BehaviorAction, BehaviorPattern, BehaviorScene
from pallas.product.llm.reply_variation import build_recent_reply_variation_hint
from pallas.product.llm.session_store import LlmChatTurn


def patch_expression_message_repository(
    monkeypatch: pytest.MonkeyPatch,
    mod,
    message_repo,
) -> None:
    import pallas.product.llm.dynamic_expression_context as dec_mod

    monkeypatch.setattr(dec_mod, "make_message_repository", lambda: message_repo)


def patch_expression_trigger_keywords(
    monkeypatch: pytest.MonkeyPatch,
    mod,
    keywords_fn,
) -> None:
    import pallas.product.llm.dynamic_expression_context as dec_mod

    monkeypatch.setattr(dec_mod, "extract_chat_trigger_keywords", keywords_fn)
    monkeypatch.setattr(mod, "extract_chat_trigger_keywords", keywords_fn)


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_prefers_topical_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    answers = [
        SimpleNamespace(messages=["那确实"], keywords="明日方舟 六星", count=4),
        SimpleNamespace(messages=["行啊"], keywords="吃饭 下班", count=9),
        SimpleNamespace(messages=["你这波有点狠"], keywords="明日方舟 抽卡", count=3),
    ]

    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=answers))
    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    monkeypatch.setattr(
        mod,
        "extract_chat_trigger_keywords",
        lambda text: ["明日方舟", "抽卡"] if text == "这次抽卡也太黑了" else [],
    )

    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了")

    assert hint == "\n【语料收尾参考】当前话题可参考本群常接的短句：你这波有点狠、那确实。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_prefers_recent_live_group_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    now = int(time.time())
    answers = [
        SimpleNamespace(messages=["那确实"], keywords="明日方舟 六星", count=9),
        SimpleNamespace(messages=["也不是不行"], keywords="明日方舟 抽卡", count=8),
    ]
    recent_messages = [
        SimpleNamespace(
            group_id=20002,
            user_id=111,
            bot_id=10001,
            raw_message="这也太黑了吧",
            is_plain_text=True,
            plain_text="这也太黑了吧",
            keywords="明日方舟 抽卡",
            time=now - 30,
        ),
        SimpleNamespace(
            group_id=20002,
            user_id=111,
            bot_id=10001,
            raw_message="你这波有点狠",
            is_plain_text=True,
            plain_text="你这波有点狠",
            keywords="明日方舟 抽卡",
            time=now - 20,
        ),
        SimpleNamespace(
            group_id=20002,
            user_id=222,
            bot_id=10001,
            raw_message="谢谢你呀",
            is_plain_text=True,
            plain_text="谢谢你呀",
            keywords="明日方舟 抽卡",
            time=now - 10,
        ),
    ]

    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=answers))
    message_repo = SimpleNamespace(find_recent_in_group=AsyncMock(return_value=recent_messages))
    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    patch_expression_message_repository(monkeypatch, mod, message_repo)
    patch_expression_trigger_keywords(monkeypatch, mod, lambda _text: ["明日方舟", "抽卡"])

    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了吧？？？")

    assert hint == "\n【语料收尾参考】当前话题可参考本群最近常接的短句：这也太黑了吧、你这波有点狠。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_skips_bot_and_current_user_in_recent_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    now = int(time.time())
    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=[]))
    recent_messages = [
        SimpleNamespace(
            group_id=20002,
            user_id=30003,
            bot_id=10001,
            raw_message="这也太黑了吧",
            is_plain_text=True,
            plain_text="这也太黑了吧",
            keywords="明日方舟 抽卡",
            time=now - 30,
        ),
        SimpleNamespace(
            group_id=20002,
            user_id=444,
            bot_id=10001,
            raw_message="你这波有点狠",
            is_plain_text=True,
            plain_text="你这波有点狠",
            keywords="明日方舟 抽卡",
            time=now - 20,
        ),
        SimpleNamespace(
            group_id=20002,
            user_id=555,
            bot_id=10001,
            raw_message="这波真的黑",
            is_plain_text=True,
            plain_text="这波真的黑",
            keywords="明日方舟 抽卡",
            time=now - 10,
        ),
    ]
    message_repo = SimpleNamespace(find_recent_in_group=AsyncMock(return_value=recent_messages))

    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    patch_expression_message_repository(monkeypatch, mod, message_repo)
    patch_expression_trigger_keywords(monkeypatch, mod, lambda _text: ["明日方舟", "抽卡"])

    hint = await mod.build_llm_chat_corpus_ending_hint(
        20002,
        "这次抽卡也太黑了吧？？？",
        bot_id=10001,
        current_user_id=30003,
    )

    assert hint == "\n【语料收尾参考】当前话题可参考本群最近常接的短句：这波真的黑、你这波有点狠。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_prefers_topic_run_from_same_recent_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    now = int(time.time())
    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=[]))
    recent_messages = [
        SimpleNamespace(
            group_id=20002,
            user_id=777,
            bot_id=10001,
            raw_message="这也太黑了吧",
            is_plain_text=True,
            plain_text="这也太黑了吧",
            keywords="明日方舟 抽卡",
            time=now - 40,
        ),
        SimpleNamespace(
            group_id=20002,
            user_id=777,
            bot_id=10001,
            raw_message="你这波有点狠",
            is_plain_text=True,
            plain_text="你这波有点狠",
            keywords="明日方舟 抽卡",
            time=now - 30,
        ),
        SimpleNamespace(
            group_id=20002,
            user_id=888,
            bot_id=10001,
            raw_message="那确实",
            is_plain_text=True,
            plain_text="那确实",
            keywords="明日方舟 抽卡",
            time=now - 10,
        ),
    ]
    message_repo = SimpleNamespace(find_recent_in_group=AsyncMock(return_value=recent_messages))

    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    patch_expression_message_repository(monkeypatch, mod, message_repo)
    patch_expression_trigger_keywords(monkeypatch, mod, lambda _text: ["明日方舟", "抽卡"])

    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了吧？？？")

    assert hint == "\n【语料收尾参考】当前话题可参考本群最近常接的短句：这也太黑了吧、你这波有点狠。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_ignores_repeater_bundle_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    now = int(time.time())
    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=[]))
    recent_messages = [
        SimpleNamespace(
            group_id=20002,
            user_id=888,
            bot_id=10001,
            raw_message="那确实",
            is_plain_text=True,
            plain_text="那确实",
            keywords="明日方舟 抽卡",
            time=now - 10,
        ),
    ]
    message_repo = SimpleNamespace(find_recent_in_group=AsyncMock(return_value=recent_messages))

    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    patch_expression_message_repository(monkeypatch, mod, message_repo)
    patch_expression_trigger_keywords(monkeypatch, mod, lambda _text: ["明日方舟", "抽卡"])
    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了吧？？？")

    assert hint == "\n【语料收尾参考】当前话题可参考本群最近常接的短句：那确实。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_unifies_recent_and_answer_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    now = int(time.time())
    repo = SimpleNamespace(
        list_answers_for_group_since=AsyncMock(
            return_value=[
                SimpleNamespace(messages=["这也太黑了吧"], keywords="明日方舟 抽卡", count=8),
                SimpleNamespace(messages=["你这波有点狠"], keywords="明日方舟 抽卡", count=6),
            ]
        )
    )
    message_repo = SimpleNamespace(
        find_recent_in_group=AsyncMock(
            return_value=[
                SimpleNamespace(
                    group_id=20002,
                    user_id=111,
                    bot_id=10001,
                    raw_message="那确实",
                    is_plain_text=True,
                    plain_text="那确实",
                    keywords="明日方舟 抽卡",
                    time=now - 20,
                ),
            ]
        )
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    patch_expression_message_repository(monkeypatch, mod, message_repo)
    patch_expression_trigger_keywords(monkeypatch, mod, lambda _text: ["明日方舟", "抽卡"])
    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了吧？？？")

    assert hint == "\n【语料收尾参考】当前话题可参考本群最近常接的短句：那确实、这也太黑了吧、你这波有点狠。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_dedupes_similar_endings(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=[]))
    message_repo = SimpleNamespace(find_recent_in_group=AsyncMock(return_value=[]))

    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    patch_expression_message_repository(monkeypatch, mod, message_repo)
    patch_expression_trigger_keywords(monkeypatch, mod, lambda _text: ["明日方舟", "抽卡"])
    repo = SimpleNamespace(
        list_answers_for_group_since=AsyncMock(
            return_value=[
                SimpleNamespace(messages=["这也太黑了吧"], keywords="明日方舟 抽卡", count=8),
                SimpleNamespace(messages=["这也太离谱了吧"], keywords="明日方舟 抽卡", count=7),
                SimpleNamespace(messages=["你这波有点狠"], keywords="明日方舟 抽卡", count=6),
            ]
        )
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )

    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了吧？？？")

    assert hint == "\n【语料收尾参考】当前话题可参考本群常接的短句：这也太黑了吧、你这波有点狠。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_prefers_affect_aligned_topical_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    answers = [
        SimpleNamespace(messages=["这也太黑了吧"], keywords="明日方舟 抽卡", count=4),
        SimpleNamespace(messages=["那确实"], keywords="明日方舟 抽卡", count=9),
        SimpleNamespace(messages=["谢谢你呀"], keywords="明日方舟 抽卡", count=6),
    ]

    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=answers))
    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    monkeypatch.setattr(mod, "extract_chat_trigger_keywords", lambda _text: ["明日方舟", "抽卡"])

    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了吧？？？")

    assert hint == "\n【语料收尾参考】当前话题可参考本群常接的短句：这也太黑了吧。"


@pytest.mark.asyncio
async def test_build_llm_chat_corpus_ending_hint_falls_back_to_hot_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    answers = [
        SimpleNamespace(messages=["行啊"], keywords="吃饭 下班", count=9),
        SimpleNamespace(messages=["也不是不行"], keywords="夜宵", count=7),
    ]

    repo = SimpleNamespace(list_answers_for_group_since=AsyncMock(return_value=answers))
    monkeypatch.setitem(
        __import__("sys").modules,
        "pallas.core.foundation.db.context_repo_access",
        SimpleNamespace(get_shared_context_repository=lambda: repo),
    )
    monkeypatch.setattr(mod, "extract_chat_trigger_keywords", lambda _text: ["明日方舟"])

    hint = await mod.build_llm_chat_corpus_ending_hint(20002, "这次抽卡也太黑了")

    assert hint == "\n【语料收尾参考】本群常见短句可参考：行啊、也不是不行。"


def test_build_recent_reply_variation_hint_flags_repeated_structure_without_exact_duplicate() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="其实这事可以慢慢来，你先别急。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="感觉这事不用一下说满，你先收一收。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="确实不用讲太整套，你先按这个做。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头" in hint
    assert "最近解释偏满，这轮优先短一点，像顺手接一句" in hint
    assert "最近句式有点一个模子" in hint


def test_build_recent_reply_variation_hint_flags_repeated_laugh_opener() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="哈哈，这事还真挺怪。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="哈哈，先别急。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="哈哈哈，你这波也太巧了。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头：哈哈类" in hint


def test_build_recent_reply_variation_hint_flags_repeated_sigh_opener() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="欸，这也太巧了。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="哎，先别急。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="唉，你这波真离谱。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头：语气词类" in hint


def test_build_recent_reply_variation_hint_flags_generic_prefix_cluster() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="行吧，那就先这样。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="行吧，你先忙。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="行吧，回头再说。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头：行吧" in hint


@pytest.mark.asyncio
async def test_handle_llm_chat_skips_empty_to_me_without_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        reply=None,
        raw_message="[CQ:at,qq=10001]",
        get_plaintext=lambda: "",
        get_message=lambda: "",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    send_mock = AsyncMock()
    submit_mock = AsyncMock()

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(mod.llm_chat_msg, "send", send_mock)
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    send_mock.assert_not_awaited()
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_llm_chat_records_route_and_fallback_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        raw_message="[CQ:at,qq=10001] 你好",
        get_plaintext=lambda: "你好",
        get_message=lambda: "[CQ:at,qq=10001] 你好",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    added: dict[str, object] = {}

    async def fake_add_task(task_id: str, payload: dict) -> None:
        added["task_id"] = task_id
        added["payload"] = payload

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(
            llm_chat_system_prompt_path="",
            llm_chat_min_priority=40,
        ),
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_rag_enabled=False,
            llm_relationship_notes_enabled=False,
            llm_chat_enabled=True,
            llm_select_enabled=True,
            llm_polish_lite_enabled=False,
            llm_polish_enabled=False,
            llm_chat_cooldown_sec=3,
            llm_chat_queue_merge=True,
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(
            return_value=(
                SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})),
                None,
                None,
            )
        ),
    )
    monkeypatch.setattr(
        mod,
        "enrich_system_with_memory_context",
        AsyncMock(side_effect=lambda prompt, **_: SimpleNamespace(system_prompt=prompt, trace={"hit_count": 1})),
    )
    monkeypatch.setattr(
        mod,
        "enrich_system_with_knowledge_sources",
        AsyncMock(side_effect=lambda prompt, **_: SimpleNamespace(system_prompt=prompt, trace={"hit_count": 0})),
    )
    monkeypatch.setattr(
        mod,
        "enrich_system_with_relationship_context",
        AsyncMock(side_effect=lambda prompt, **_: SimpleNamespace(system_prompt=prompt, trace={"hit_count": 0})),
    )
    monkeypatch.setattr(
        mod,
        "build_llm_chat_expression_suffix",
        AsyncMock(return_value="\n【表达习惯参考】群里常接这些说法/梗：牛牛税。"),
    )
    monkeypatch.setattr(
        mod,
        "build_llm_chat_ending_hint",
        lambda *_args, **_kwargs: "\n【收尾变化参考】这轮可优先试试这些自然收口：行啊、也不是不行、那确实。",
    )
    monkeypatch.setattr(
        mod,
        "build_llm_chat_dynamic_expression_hint",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        mod,
        "build_llm_chat_corpus_ending_hint",
        AsyncMock(return_value="\n【语料收尾参考】当前话题可参考本群常接的短句：行啊、那确实。"),
    )
    monkeypatch.setattr(
        mod,
        "classify_behavior_scene",
        lambda **_kwargs: BehaviorScene.PROVOCATION,
    )
    monkeypatch.setattr(
        mod,
        "list_behavior_patterns",
        lambda: [
            BehaviorPattern(
                pattern_id="p1",
                scene=BehaviorScene.PROVOCATION,
                action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
                scope_group_id=20002,
                success_score=3,
            )
        ],
    )
    monkeypatch.setattr(mod, "GroupMessageEvent", SimpleNamespace)
    monkeypatch.setattr(mod, "resolve_conversation_feature_level", lambda *_args, **_kwargs: "full_conversation_kernel")
    monkeypatch.setattr(mod, "can_read_behavioral_learning", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(mod, "evaluate_llm_reply_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "refresh_llm_chat_cooldown", AsyncMock())
    monkeypatch.setattr(
        mod,
        "merge_queued_chat",
        lambda *_args, **_kwargs: SimpleNamespace(text="[CQ:at,qq=10001] 你好", merged=False),
    )
    monkeypatch.setattr(
        mod,
        "list_user_llm_messages",
        AsyncMock(
            return_value=[
                SimpleNamespace(role="assistant", content="其实就是这样", user_id=30003, created_at=1),
                SimpleNamespace(role="assistant", content="其实也行", user_id=30003, created_at=2),
                SimpleNamespace(role="assistant", content="其实差不多。", user_id=30003, created_at=3),
            ]
        ),
    )
    monkeypatch.setattr(mod, "latest_llm_assistant_reply", AsyncMock(return_value="上一句"))
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)
    monkeypatch.setattr(mod.TaskManager, "add_task", fake_add_task)

    bundle = SimpleNamespace(
        message_pool=["候选一", "候选二"],
        answer_list=["候选一"],
    )

    class FakeChat:
        def __init__(self, _event):
            pass

        async def find_reply_bundle(self):
            return bundle

    monkeypatch.setitem(
        __import__("sys").modules,
        "packages.repeater.model",
        SimpleNamespace(Chat=FakeChat, ChatData=SimpleNamespace),
    )
    monkeypatch.setattr(mod, "maybe_submit_repeater_corpus_llm", AsyncMock(return_value=False))

    await mod.handle_llm_chat(bot, event)

    payload = added["payload"]
    assert isinstance(payload, dict)
    assert payload["task_type"] == "llm_chat"
    assert payload["fallback_text"] == "候选一"
    assert payload["llm_route"] == "corpus_select"
    assert payload["last_reply_text"] == "上一句"
    assert "最近几轮别再用这些开头" in payload["variation_hint"]
    assert payload["behavior_scene"] == "provocation"
    assert payload["behavior_pattern_ids"] == ["p1"]
    assert payload["behavior_actions"] == ["light_tease_and_close"]
    assert payload["behavior_hint"] == ""
    submit_request = submit_mock.await_args.args[0]
    assert "【本轮表达去重】" in submit_request.system_prompt
    assert "【本轮牛格塑形】" in submit_request.system_prompt
    assert "【表达习惯参考】" in submit_request.system_prompt
    assert "【收尾变化参考】" in submit_request.system_prompt
    assert "【语料收尾参考】" in submit_request.system_prompt
    assert submit_request.llm_rewrite_metadata["persona_shaping_active"] is True
    assert "【本轮牛格塑形】" in submit_request.llm_rewrite_metadata["persona_affect_block"]
    assert submit_request.hybrid_retrieval_trace["sources"] == ["memory"]


@pytest.mark.asyncio
async def test_handle_llm_chat_defers_when_user_likely_not_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        raw_message="[CQ:at,qq=10001] 等等我补一句...",
        get_plaintext=lambda: "等等我补一句...",
        get_message=lambda: "[CQ:at,qq=10001] 等等我补一句...",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(
            llm_chat_system_prompt_path="",
            llm_chat_min_priority=40,
        ),
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_rag_enabled=False,
            llm_relationship_notes_enabled=False,
            llm_chat_enabled=True,
            llm_select_enabled=False,
            llm_polish_lite_enabled=False,
            llm_polish_enabled=False,
            llm_chat_cooldown_sec=3,
            llm_chat_queue_merge=True,
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(
            return_value=(
                SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})),
                None,
                None,
            )
        ),
    )
    monkeypatch.setattr(
        mod,
        "enrich_system_with_memory_context",
        AsyncMock(side_effect=lambda prompt, **_: SimpleNamespace(system_prompt=prompt, trace={"hit_count": 0})),
    )
    monkeypatch.setattr(
        mod,
        "enrich_system_with_knowledge_sources",
        AsyncMock(side_effect=lambda prompt, **_: SimpleNamespace(system_prompt=prompt, trace={"hit_count": 0})),
    )
    monkeypatch.setattr(
        mod,
        "enrich_system_with_relationship_context",
        AsyncMock(side_effect=lambda prompt, **_: SimpleNamespace(system_prompt=prompt, trace={"hit_count": 0})),
    )
    monkeypatch.setattr(mod, "build_llm_chat_expression_suffix", AsyncMock(return_value=""))
    monkeypatch.setattr(mod, "resolve_conversation_feature_level", lambda *_args, **_kwargs: "full_conversation_kernel")
    monkeypatch.setattr(mod, "can_read_behavioral_learning", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(mod, "evaluate_llm_reply_gate", lambda *_args, **_kwargs: None)
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    submit_mock.assert_not_awaited()
