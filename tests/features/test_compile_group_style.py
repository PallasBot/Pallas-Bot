from __future__ import annotations

from pallas.product.persona.compile_group_style import (
    build_group_style_hints,
    compile_group_style_prompt,
    compile_group_style_snapshot,
)


def test_compile_group_style_snapshot_empty_profile() -> None:
    snapshot = compile_group_style_snapshot(None)
    assert snapshot["ready"] is False
    assert snapshot["signals"] is None
    assert "尚无群风格画像" in snapshot["hints"][0]


def test_compile_group_style_snapshot_insufficient_sample() -> None:
    profile = {
        "version": 1,
        "updated_at": 1,
        "sample": {"message_count": 10, "answer_count": 2},
        "raw": {"avg_plain_len": 8.0},
    }
    snapshot = compile_group_style_snapshot(profile)
    assert snapshot["ready"] is False
    assert snapshot["signals"] is None
    assert "样本不足" in snapshot["hints"][0]


def test_compile_group_style_snapshot_ready_profile() -> None:
    profile = {
        "version": 1,
        "updated_at": 1710000000,
        "sample": {"message_count": 420, "answer_count": 85},
        "raw": {
            "avg_plain_len": 18.5,
            "p50_plain_len": 12,
            "msgs_per_hour_active": 9.0,
            "local_answer_ratio": 0.2,
            "repeat_chain_rate": 0.18,
        },
        "derived": {
            "reply_bias_mul": 1.12,
            "speak_bias_mul": 1.03,
            "length_pref": "short",
            "chaos_bias": 0.18,
        },
    }
    snapshot = compile_group_style_snapshot(profile)
    assert snapshot["ready"] is True
    assert snapshot["signals"]["length_pref"] == "short"
    assert snapshot["signals"]["chaos_bias"] == 0.18
    assert "群消息偏短" in snapshot["hints"]
    assert "聊天较活跃" in snapshot["hints"]


def test_build_group_style_hints_calm_long_group() -> None:
    hints = build_group_style_hints({
        "length_pref": "long",
        "msgs_per_hour_active": 2.0,
        "chaos_bias": 0.05,
        "reply_bias_mul": 0.9,
    })
    assert "群消息偏长" in hints
    assert "聊天较安静" in hints
    assert "适合更克制接话" in hints


def test_compile_group_style_prompt_ready() -> None:
    prompt = compile_group_style_prompt({
        "sample": {"message_count": 100, "answer_count": 20},
        "raw": {"msgs_per_hour_active": 6.0, "repeat_chain_rate": 0.1},
        "derived": {
            "reply_bias_mul": 1.05,
            "speak_bias_mul": 1.0,
            "length_pref": "medium",
            "chaos_bias": 0.1,
        },
    })
    assert prompt.startswith("<<STATS:group_style>>")
    assert "长度偏好=medium" in prompt
    assert "摘要：" in prompt


def test_compile_group_style_prompt_not_ready() -> None:
    prompt = compile_group_style_prompt(None)
    assert "<<STATS:group_style>>" in prompt
    assert "新群或样本尚少" in prompt
