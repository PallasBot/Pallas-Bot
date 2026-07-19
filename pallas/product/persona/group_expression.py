from __future__ import annotations

from typing import Any

from pallas.product.persona.prompt_guard import sanitize_prompt_literal, wrap_stats_block


def compile_group_expression_prompt(style_profile: dict[str, Any] | None) -> str:
    if not isinstance(style_profile, dict):
        return wrap_stats_block("group_expression", "【群聊表达习惯】样本不足，暂无稳定表达习惯。")

    sample = style_profile.get("sample") if isinstance(style_profile.get("sample"), dict) else {}
    raw = style_profile.get("raw") if isinstance(style_profile.get("raw"), dict) else {}
    derived = style_profile.get("derived") if isinstance(style_profile.get("derived"), dict) else {}
    if not derived:
        return wrap_stats_block(
            "group_expression",
            "【群聊表达习惯】新群或样本尚少：像群友口语接话，短句为主，避免客服式完整解释。",
        )

    parts: list[str] = []
    length_pref = str(derived.get("length_pref") or "").strip()
    if length_pref == "short":
        parts.append("更像顺手短句，不爱铺长解释")
    elif length_pref == "long":
        parts.append("偶尔会多说两句，但仍应保持口语")
    elif length_pref == "medium":
        parts.append("更适合两三句内说清，不必拉太长")

    chaos_bias = float(derived.get("chaos_bias") or 0.0)
    if length_pref == "short" and chaos_bias >= 0.15:
        parts.append("短句和顺手接话更自然，别一开口就解释太满")

    repeat_chain_rate = float(raw.get("repeat_chain_rate") or 0.0)
    if repeat_chain_rate >= 0.2:
        parts.append("复读链和接梗较常见，允许顺着群梗接一句")

    civility_score = float((raw.get("affect_tone") or {}).get("civility_score") or 0.0)
    if civility_score <= -0.25:
        parts.append("整体语气更直接，少一点客服式客套")
    elif civility_score >= 0.25:
        parts.append("整体语气偏客气，别故意说得太冲")

    affect_triggers = sample.get("affect_triggers") if isinstance(sample.get("affect_triggers"), list) else []
    trigger_texts = []
    for item in affect_triggers[:3]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("phrase") or item.get("trigger") or item.get("text") or "").strip()
        if text:
            trigger_texts.append(text)
    if trigger_texts:
        parts.append("群里常见触发词/梗：" + "、".join(trigger_texts))

    if not parts:
        parts.append("按本群语气自然接话，避免通用机器人式完整解释")

    body = "【群聊表达习惯】" + sanitize_prompt_literal("；".join(parts), max_len=320)
    return wrap_stats_block("group_expression", body)
