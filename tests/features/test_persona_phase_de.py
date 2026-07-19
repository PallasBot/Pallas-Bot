from __future__ import annotations

from pallas.core.foundation.db.modules import Answer, Message
from pallas.product.llm.select import filter_select_candidate_pool
from pallas.product.persona.compile_group_style import compile_group_style_snapshot
from pallas.product.persona.group_profiler import build_group_style_profile


def _msg(*, group_id: int, plain_text: str, ts: int) -> Message:
    return Message.model_construct(
        group_id=group_id,
        user_id=1,
        bot_id=114514,
        raw_message=plain_text,
        is_plain_text=True,
        plain_text=plain_text,
        keywords=plain_text,
        time=ts,
    )


def _answer(*, group_id: int, keywords: str, message: str, count: int, ts: int) -> Answer:
    return Answer(keywords=keywords, group_id=group_id, count=count, time=ts, messages=[message])


def test_build_group_style_profile_skips_contaminated_samples(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    now = 1_700_000_000
    messages = [_msg(group_id=300, plain_text="草", ts=now - 60 * i) for i in range(30)]
    messages.append(_msg(group_id=300, plain_text="希望每个庆典都能顺利", ts=now - 30))
    answers = [_answer(group_id=300, keywords=f"k{i}", message="哈哈", count=2, ts=now - 45 * i) for i in range(8)]
    answers.append(_answer(group_id=300, keywords="坏", message="庆典感满满", count=3, ts=now - 20))

    profile = build_group_style_profile(group_id=300, messages=messages, answers=answers, now_ts=now)

    assert profile["sample"]["message_count"] == 30
    assert profile["sample"]["answer_count"] == 8
    assert profile["sample"]["contamination_skipped"]["message_count"] == 1
    assert profile["sample"]["contamination_skipped"]["answer_count"] == 1


def test_compile_group_style_snapshot_exposes_contamination_skipped_count() -> None:
    snapshot = compile_group_style_snapshot({
        "updated_at": 1,
        "sample": {
            "message_count": 10,
            "answer_count": 5,
            "contamination_skipped": {"message_count": 2, "answer_count": 1},
        },
        "derived": {"reply_bias_mul": 1.0, "length_pref": "short"},
        "raw": {},
    })
    assert snapshot["contamination_skipped_count"] == 3


def test_filter_select_candidate_pool_skips_contaminated(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    safe, diag = filter_select_candidate_pool(["这也太黑了吧", "希望每个庆典都能顺利", "那确实"])
    assert safe == ["这也太黑了吧", "那确实"]
    assert diag["skipped_contamination"] == 1
