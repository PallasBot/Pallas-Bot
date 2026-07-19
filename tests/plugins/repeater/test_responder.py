import asyncio
from collections import defaultdict, deque
from operator import itemgetter
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from pallas.core.platform.shard.repeater_ingress_metrics import (
    clear_repeater_ingress_metrics_for_tests,
    repeater_ingress_metrics_snapshot,
)


class _Config:
    def __init__(self, value: int):
        self._value = value

    async def drunkenness(self) -> int:
        return self._value


def _pick_weighted_max(seq, weights):
    return [seq[weights.index(max(weights))]]


@pytest.mark.asyncio
async def test_context_find_repeat_detection():
    from packages.repeater.responder import Responder

    group_id = 111
    bot_id = 222
    raw_message = "repeat_me"
    keywords = "repeat_kw"
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message=raw_message,
        keywords=keywords,
        bot_id=bot_id,
        keywords_len=2,
        to_me=False,
        is_image=False,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][bot_id] = [{"reply": "other", "reply_keywords": "other"}]
    message_dict = defaultdict(list)
    human = 90001
    message_dict[group_id] = [
        SimpleNamespace(raw_message="x", user_id=human),
        SimpleNamespace(raw_message=raw_message, user_id=human),
        SimpleNamespace(raw_message=raw_message, user_id=human),
    ]
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with (
            patch("packages.repeater.responder.get_bots", return_value={}),
            patch("packages.repeater.responder.context_repo.find_by_keywords", new_callable=AsyncMock) as mock_find_one,
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result == ([raw_message], keywords)
            mock_find_one.assert_not_called()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_repeat_not_triggered_when_tail_is_only_bots():
    """尾部相同句来自本进程其它 Bot QQ 时不应判为复读。"""
    from packages.repeater.responder import Responder

    group_id = 201
    bot_id = 202
    other_bot_qq = 203
    raw_message = "same_line"
    keywords = "kw"
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message=raw_message,
        plain_text=raw_message,
        keywords=keywords,
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][bot_id] = [{"reply": "other", "reply_keywords": "other"}]
    human = 90002
    message_dict = defaultdict(list)
    message_dict[group_id] = [
        SimpleNamespace(raw_message="noise", user_id=human),
        SimpleNamespace(raw_message=raw_message, user_id=other_bot_qq),
        SimpleNamespace(raw_message=raw_message, user_id=other_bot_qq),
    ]
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    fake_bot = SimpleNamespace(self_id=other_bot_qq)

    try:
        with (
            patch("packages.repeater.responder.get_bots", return_value={"b1": fake_bot}),
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=None,
                create=True,
            ) as mock_find,
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
            mock_find.assert_called_once()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_repeat_skips_repeat_ignore_user_ids_config():
    """配置 repeat_ignore_user_ids 中的 QQ 不计入复读条数。"""
    from packages.repeater import responder as responder_mod
    from packages.repeater.responder import Responder

    group_id = 301
    bot_id = 302
    external_bot = 303303
    raw_message = "line"
    keywords = "kw2"
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message=raw_message,
        plain_text=raw_message,
        keywords=keywords,
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][bot_id] = [{"reply": "other", "reply_keywords": "other"}]
    human = 90003
    message_dict = defaultdict(list)
    message_dict[group_id] = [
        SimpleNamespace(raw_message="noise", user_id=human),
        SimpleNamespace(raw_message=raw_message, user_id=external_bot),
        SimpleNamespace(raw_message=raw_message, user_id=external_bot),
    ]
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with (
            patch.object(responder_mod.plugin_config, "repeat_ignore_user_ids", [external_bot]),
            patch("packages.repeater.responder.get_bots", return_value={}),
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=None,
                create=True,
            ) as mock_find,
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
            mock_find.assert_called_once()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_returns_none_no_context():
    from packages.repeater.responder import Responder

    group_id = 123
    bot_id = 456
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="hello",
        keywords="hello_kw",
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
            new_callable=AsyncMock,
            return_value=None,
            create=True,
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_skips_repo_lookup_when_keywords_empty():
    from packages.repeater.responder import Responder

    group_id = 124
    bot_id = 457
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="[CQ:image,url=x]",
        keywords="",
        bot_id=bot_id,
        keywords_len=0,
        to_me=False,
        is_image=False,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
            new_callable=AsyncMock,
            create=True,
        ) as mock_find_reply:
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
            mock_find_reply.assert_not_called()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_skips_repo_lookup_for_long_non_plain_raw_keywords():
    from packages.repeater.responder import Responder

    group_id = 125
    bot_id = 458
    raw_message = "[CQ:json,data=" + ("x" * 320) + "]"
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message=raw_message,
        keywords=raw_message,
        bot_id=bot_id,
        keywords_len=0,
        to_me=False,
        is_image=False,
        is_plain_text=False,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
            new_callable=AsyncMock,
            create=True,
        ) as mock_find_reply:
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
            mock_find_reply.assert_not_called()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_skips_repo_lookup_for_short_plain_text_noise():
    from packages.repeater.responder import Responder

    group_id = 126
    bot_id = 459
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="草",
        plain_text="草",
        keywords="草",
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
            new_callable=AsyncMock,
            create=True,
        ) as mock_find_reply:
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
            mock_find_reply.assert_not_called()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_keeps_to_me_short_plain_text_lookup():
    from packages.repeater.responder import Responder

    group_id = 127
    bot_id = 460
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="牛牛",
        plain_text="牛牛",
        keywords="牛牛",
        bot_id=bot_id,
        keywords_len=1,
        to_me=True,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
            new_callable=AsyncMock,
            return_value=None,
            create=True,
        ) as mock_find_reply:
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
            mock_find_reply.assert_called_once_with("牛牛")
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_threshold_filtering():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer, Context

    group_id = 789
    bot_id = 321
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="ctx_input",
        plain_text="ctx_input",
        keywords="ctx_kw",
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    low_answer = Answer(keywords="ans_low", group_id=group_id, count=1, time=1, messages=["low_msg"])
    high_answer = Answer(keywords="ans_high", group_id=group_id, count=3, time=1, messages=["high_msg"])
    context = Context.model_construct(
        keywords="ctx_kw", time=1, trigger_count=1, answers=[low_answer, high_answer], ban=[], clear_time=0
    )
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    message_dict[group_id] = []
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    recent_topics[group_id] = deque(maxlen=16)

    try:
        with (
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=context,
                create=True,
            ),
            patch(
                "packages.repeater.responder.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "pallas.product.persona.resolve_persona_for_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    reply_bias=1.0,
                    speak_bias=1.0,
                    chaos_bias=0.0,
                    warmth=0.0,
                    assertiveness=0.0,
                    bluntness=0.0,
                    harsh_msg_ratio=0.0,
                    polite_msg_ratio=0.0,
                    tone="neutral",
                    length_pref="any",
                ),
            ),
            patch(
                "pallas.product.persona.loader.load_affect_triggers",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("packages.repeater.activity_gate.group_has_hosted_activity", return_value=False),
            patch("packages.repeater.responder.random.choices", side_effect=[[3], [high_answer]]),
            patch("packages.repeater.responder.random.choice", return_value="high_msg"),
            patch("packages.repeater.responder.random.random", return_value=1.0),
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result == (["high_msg"], "ans_high")
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_reply_post_proc_via_responder():
    from packages.repeater.responder import Responder

    group_id = 555
    bot_id = 666
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_lock = asyncio.Lock()
    reply_dict[group_id][bot_id] = [
        {
            "time": 1,
            "pre_raw_message": "a",
            "pre_keywords": "a",
            "reply": "old",
            "reply_keywords": "a",
        }
    ]

    try:
        ok = await Responder.reply_post_proc("old", "new", bot_id, group_id, reply_dict, reply_lock)
        assert ok is True
        assert reply_dict[group_id][bot_id][0]["reply"] == "new"
    finally:
        reply_dict.clear()


def test_choose_reply_mode_prefers_ghost_when_chaos_bias_is_high():
    from packages.repeater.responder import Responder
    from pallas.product.persona.model import ResolvedPersona

    persona = ResolvedPersona(chaos_bias=0.85)
    assert Responder._choose_reply_mode(persona, group_activity=0.95, to_me=False) == "ghost"


def test_choose_reply_mode_prefers_god_for_low_chaos_active_group():
    from packages.repeater.responder import Responder
    from pallas.product.persona.model import ResolvedPersona

    persona = ResolvedPersona(chaos_bias=0.05, reply_bias=1.15, warmth=0.1)
    assert Responder._choose_reply_mode(persona, group_activity=0.9, to_me=False) == "god"


def test_choose_reply_mode_keeps_normal_when_called_to_me():
    from packages.repeater.responder import Responder
    from pallas.product.persona.model import ResolvedPersona

    persona = ResolvedPersona(chaos_bias=0.9, reply_bias=1.2)
    assert Responder._choose_reply_mode(persona, group_activity=1.0, to_me=True) == "normal"


def test_roll_active_mode_is_occasional():
    from unittest.mock import patch

    from packages.repeater.responder import Responder

    with patch("packages.repeater.responder.random.random", return_value=0.99):
        assert Responder._roll_active_mode("god") == "normal"
        assert Responder._roll_active_mode("ghost") == "normal"
    with patch("packages.repeater.responder.random.random", return_value=0.0):
        assert Responder._roll_active_mode("god") == "god"
        assert Responder._roll_active_mode("ghost") == "ghost"
    # normal 永远不掷骰子
    assert Responder._roll_active_mode("normal") == "normal"


def test_answer_weight_prefers_god_style_for_popular_recent_human_reply():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer
    from pallas.product.persona.model import ResolvedPersona

    persona = ResolvedPersona(chaos_bias=0.05, warmth=0.15, assertiveness=0.1)
    answer = Answer(
        keywords="kw",
        group_id=1,
        count=6,
        time=1,
        messages=["懂了这波真行", "也不是不行"],
    )
    recent_sent = ["别的句子"]
    recent_message = ["懂了这波真行", "路过"]

    god_weight = Responder._answer_weight_for_mode(
        answer,
        persona,
        recent_sent=recent_sent,
        recent_message=recent_message,
        affect_triggers=[],
        mode="god",
    )
    normal_weight = Responder._answer_weight_for_mode(
        answer,
        persona,
        recent_sent=recent_sent,
        recent_message=recent_message,
        affect_triggers=[],
        mode="normal",
    )

    assert god_weight > normal_weight


def test_answer_weight_prefers_ghost_style_for_short_odd_reply():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer
    from pallas.product.persona.model import ResolvedPersona

    persona = ResolvedPersona(chaos_bias=0.8, bluntness=0.3, length_pref="short", tone="terse")
    answer = Answer(
        keywords="kw",
        group_id=1,
        count=2,
        time=1,
        messages=["寄", "有点那个"],
    )

    ghost_weight = Responder._answer_weight_for_mode(
        answer,
        persona,
        recent_sent=[],
        recent_message=["路过"],
        affect_triggers=[],
        mode="ghost",
    )
    normal_weight = Responder._answer_weight_for_mode(
        answer,
        persona,
        recent_sent=[],
        recent_message=["路过"],
        affect_triggers=[],
        mode="normal",
    )

    assert ghost_weight > normal_weight


def test_collect_god_candidate_pool_excludes_recent_live_texts():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer

    answer = Answer(
        keywords="kw",
        group_id=1,
        count=5,
        time=1,
        messages=["存量句子", "懂了这波真行"],
    )
    recent_message = ["懂了这波真行", "路过", "懂了这波真行", "来个补刀"]

    pool = Responder._collect_mode_candidate_pool(
        answer,
        mode="god",
        recent_message=recent_message,
    )

    # 神模式不跟读群里此刻在刷的原话
    assert "懂了这波真行" not in pool
    assert pool == ["存量句子"]


def test_collect_ghost_candidate_pool_prefers_short_odd_texts():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer

    answer = Answer(
        keywords="kw",
        group_id=1,
        count=4,
        time=1,
        messages=["这也太正常了吧", "寄", "有点那个"],
    )

    pool = Responder._collect_mode_candidate_pool(
        answer,
        mode="ghost",
        recent_message=["路过"],
    )

    assert pool[0] == "寄"
    assert "有点那个" in pool


def test_feedback_bias_multiplier_defaults_to_identity():
    from packages.repeater.responder import Responder

    mult = Responder._feedback_bias_multiplier(
        "少来。",
        feedback_snapshot={"count": 0, "top_replies": [], "scenes": []},
    )

    assert mult == 1.0


def test_feedback_bias_multiplier_boosts_matching_short_reply():
    from packages.repeater.responder import Responder

    mult = Responder._feedback_bias_multiplier(
        "少来。",
        feedback_snapshot={"count": 4, "top_replies": ["少来。", "行吧"], "scenes": ["banter"]},
    )

    assert mult > 1.0


def test_feedback_bias_multiplier_ignores_sparse_feedback():
    from packages.repeater.responder import Responder

    mult = Responder._feedback_bias_multiplier(
        "少来。",
        feedback_snapshot={"count": 1, "top_replies": ["少来。"], "scenes": ["banter"], "matched_replies": []},
    )

    assert mult == 1.0


def test_feedback_bias_multiplier_boosts_trigger_matched_reply_with_single_sample():
    from packages.repeater.responder import Responder

    mult = Responder._feedback_bias_multiplier(
        "别闹",
        feedback_snapshot={
            "count": 1,
            "top_replies": [],
            "matched_replies": ["别闹"],
            "scenes": ["banter"],
        },
    )

    assert mult == Responder.FEEDBACK_BIAS_MATCHED_MULTIPLIER


def test_feedback_bias_multiplier_partial_match_top_reply():
    from packages.repeater.responder import Responder

    mult = Responder._feedback_bias_multiplier(
        "真的少来。",
        feedback_snapshot={
            "count": 3,
            "top_replies": ["少来。"],
            "matched_replies": [],
            "scenes": ["banter"],
        },
    )

    assert mult == Responder.FEEDBACK_BIAS_PARTIAL_MULTIPLIER


@pytest.mark.asyncio
async def test_context_find_applies_llm_feedback_bias_only_when_enabled():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer, Context

    group_id = 951
    bot_id = 952
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="你又来这套",
        plain_text="你又来这套",
        keywords="来这套",
        bot_id=bot_id,
        keywords_len=2,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    low_answer = Answer(keywords="ans_low", group_id=group_id, count=3, time=1, messages=["行吧"])
    boosted_answer = Answer(keywords="ans_bias", group_id=group_id, count=3, time=1, messages=["少来。"])
    context = Context.model_construct(
        keywords="来这套",
        time=1,
        trigger_count=1,
        answers=[low_answer, boosted_answer],
        ban=[],
        clear_time=0,
    )
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    message_dict[group_id] = [SimpleNamespace(raw_message="你又来这套", user_id=10001)]
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    recent_topics[group_id] = deque(maxlen=16)
    persona = SimpleNamespace(
        reply_bias=1.0,
        speak_bias=1.0,
        chaos_bias=0.0,
        warmth=0.0,
        assertiveness=0.0,
        bluntness=0.0,
        harsh_msg_ratio=0.0,
        polite_msg_ratio=0.0,
        tone="neutral",
        length_pref="any",
    )

    async def run_once(*, bias_enabled: bool):
        with (
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=context,
                create=True,
            ),
            patch(
                "packages.repeater.responder.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "pallas.product.persona.resolve_persona_for_message",
                new_callable=AsyncMock,
                return_value=persona,
            ),
            patch(
                "pallas.product.persona.loader.load_affect_triggers",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("packages.repeater.activity_gate.group_has_hosted_activity", return_value=False),
            patch(
                "packages.repeater.responder.can_apply_feedback_bias",
                return_value=bias_enabled,
            ),
            patch(
                "packages.repeater.responder.group_feedback_bias_snapshot",
                return_value={"count": 5, "top_replies": ["少来。"], "scenes": ["banter"]},
            ) as mock_feedback,
            patch("packages.repeater.responder.random.choices", side_effect=_pick_weighted_max),
            patch("packages.repeater.responder.random.choice", side_effect=itemgetter(0)),
            patch("packages.repeater.responder.random.random", return_value=1.0),
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            return result, mock_feedback.call_count

    try:
        disabled_result, disabled_calls = await run_once(bias_enabled=False)
        enabled_result, enabled_calls = await run_once(bias_enabled=True)

        assert disabled_result == (["行吧"], "ans_low")
        assert enabled_result == (["少来。"], "ans_bias")
        assert disabled_calls == 0
        assert enabled_calls == 1
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_feedback_snapshot_failure_preserves_baseline_behavior():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer, Context

    group_id = 961
    bot_id = 962
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="你又来这套",
        plain_text="你又来这套",
        keywords="来这套",
        bot_id=bot_id,
        keywords_len=2,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    low_answer = Answer(keywords="ans_low", group_id=group_id, count=3, time=1, messages=["行吧"])
    boosted_answer = Answer(keywords="ans_bias", group_id=group_id, count=3, time=1, messages=["少来。"])
    context = Context.model_construct(
        keywords="来这套",
        time=1,
        trigger_count=1,
        answers=[low_answer, boosted_answer],
        ban=[],
        clear_time=0,
    )
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    message_dict[group_id] = [SimpleNamespace(raw_message="你又来这套", user_id=10001)]
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    recent_topics[group_id] = deque(maxlen=16)
    persona = SimpleNamespace(
        reply_bias=1.0,
        speak_bias=1.0,
        chaos_bias=0.0,
        warmth=0.0,
        assertiveness=0.0,
        bluntness=0.0,
        harsh_msg_ratio=0.0,
        polite_msg_ratio=0.0,
        tone="neutral",
        length_pref="any",
    )

    try:
        with (
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=context,
                create=True,
            ),
            patch(
                "packages.repeater.responder.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "pallas.product.persona.resolve_persona_for_message",
                new_callable=AsyncMock,
                return_value=persona,
            ),
            patch(
                "pallas.product.persona.loader.load_affect_triggers",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("packages.repeater.activity_gate.group_has_hosted_activity", return_value=False),
            patch(
                "packages.repeater.responder.can_apply_feedback_bias",
                return_value=True,
            ),
            patch(
                "packages.repeater.responder.group_feedback_bias_snapshot",
                side_effect=RuntimeError("broken snapshot"),
            ),
            patch("packages.repeater.responder.random.choices", side_effect=_pick_weighted_max),
            patch("packages.repeater.responder.random.choice", side_effect=itemgetter(0)),
            patch("packages.repeater.responder.random.random", return_value=1.0),
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )

        assert result == (["行吧"], "ans_low")
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_sparse_feedback_does_not_bias_selection():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer, Context

    group_id = 971
    bot_id = 972
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="你又来这套",
        plain_text="你又来这套",
        keywords="来这套",
        bot_id=bot_id,
        keywords_len=2,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    low_answer = Answer(keywords="ans_low", group_id=group_id, count=3, time=1, messages=["行吧"])
    boosted_answer = Answer(keywords="ans_bias", group_id=group_id, count=3, time=1, messages=["少来。"])
    context = Context.model_construct(
        keywords="来这套",
        time=1,
        trigger_count=1,
        answers=[low_answer, boosted_answer],
        ban=[],
        clear_time=0,
    )
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    message_dict[group_id] = [SimpleNamespace(raw_message="你又来这套", user_id=10001)]
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    recent_topics[group_id] = deque(maxlen=16)
    persona = SimpleNamespace(
        reply_bias=1.0,
        speak_bias=1.0,
        chaos_bias=0.0,
        warmth=0.0,
        assertiveness=0.0,
        bluntness=0.0,
        harsh_msg_ratio=0.0,
        polite_msg_ratio=0.0,
        tone="neutral",
        length_pref="any",
    )

    try:
        with (
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=context,
                create=True,
            ),
            patch(
                "packages.repeater.responder.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "pallas.product.persona.resolve_persona_for_message",
                new_callable=AsyncMock,
                return_value=persona,
            ),
            patch(
                "pallas.product.persona.loader.load_affect_triggers",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("packages.repeater.activity_gate.group_has_hosted_activity", return_value=False),
            patch(
                "packages.repeater.responder.can_apply_feedback_bias",
                return_value=True,
            ),
            patch(
                "packages.repeater.responder.group_feedback_bias_snapshot",
                return_value={"count": 1, "top_replies": ["少来。"], "scenes": ["banter"]},
            ),
            patch("packages.repeater.responder.random.choices", side_effect=_pick_weighted_max),
            patch("packages.repeater.responder.random.choice", side_effect=itemgetter(0)),
            patch("packages.repeater.responder.random.random", return_value=1.0),
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )

        assert result == (["行吧"], "ans_low")
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_records_reply_mode_metrics():
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer, Context

    clear_repeater_ingress_metrics_for_tests()
    group_id = 901
    bot_id = 902
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="来点接话",
        plain_text="来点接话",
        keywords="接话",
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
        is_plain_text=True,
    )
    config = _Config(0)
    god_answer = Answer(keywords="ans_god", group_id=group_id, count=6, time=1, messages=["懂了这波真行"])
    context = Context.model_construct(
        keywords="接话", time=1, trigger_count=1, answers=[god_answer], ban=[], clear_time=0
    )
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    message_dict[group_id] = [
        SimpleNamespace(raw_message="懂了这波真行", user_id=10001),
        SimpleNamespace(raw_message="路过", user_id=10002),
        SimpleNamespace(raw_message="懂了这波真行", user_id=10003),
        SimpleNamespace(raw_message="确实", user_id=10005),
        SimpleNamespace(raw_message="这下对了", user_id=10006),
        SimpleNamespace(raw_message="继续", user_id=10007),
        SimpleNamespace(raw_message="有道理", user_id=10008),
        SimpleNamespace(raw_message="笑死", user_id=10009),
        SimpleNamespace(raw_message="来点接话", user_id=10004),
    ]
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    recent_topics[group_id] = deque(maxlen=16)
    trace_rows: list[dict[str, object]] = []

    try:
        with (
            patch(
                "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
                new_callable=AsyncMock,
                return_value=context,
                create=True,
            ),
            patch(
                "packages.repeater.responder.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "pallas.product.persona.resolve_persona_for_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    reply_bias=1.1,
                    speak_bias=1.0,
                    chaos_bias=0.05,
                    warmth=0.1,
                    assertiveness=0.1,
                    bluntness=0.0,
                    harsh_msg_ratio=0.0,
                    polite_msg_ratio=0.0,
                    tone="neutral",
                    length_pref="any",
                ),
            ),
            patch(
                "pallas.product.persona.loader.load_affect_triggers",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("packages.repeater.activity_gate.group_has_hosted_activity", return_value=False),
            patch("packages.repeater.responder.random.choices", side_effect=[[3], [god_answer]]),
            patch("packages.repeater.responder.random.choice", return_value="懂了这波真行"),
            patch("packages.repeater.responder.random.random", return_value=0.0),
            patch(
                "packages.repeater.responder.append_repeater_opportunity_trace",
                side_effect=lambda row: trace_rows.append(dict(row)) or True,
            ),
        ):
            bundle = await Responder.find_reply_bundle(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert bundle is not None
            assert bundle.reply_mode == "god"
            assert bundle.reply_source == "same_group"
            snap = repeater_ingress_metrics_snapshot()
            assert snap["reply_total"] == 1
            assert snap["reply_mode_god"] == 1
            assert snap["reply_source_same_group"] == 1
            assert snap["reply_pick_god_pool"] == 1
            assert trace_rows
            assert trace_rows[0]["kind"] == "repeater_reply_bundle"
            assert trace_rows[0]["reply_mode"] == "god"
            assert trace_rows[0]["pick_path"] == "god_pool"
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()
