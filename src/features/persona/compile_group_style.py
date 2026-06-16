from __future__ import annotations

from typing import Any

from .prompt_guard import (
    ALLOWED_LENGTH_PREFS,
    format_safe_decimal,
    normalize_enum,
    sanitize_prompt_literal,
    wrap_stats_block,
)

_SNAPSHOT_VERSION = 1


def compile_group_style_snapshot(style_profile: dict[str, Any] | None) -> dict[str, Any]:
    """将 group_config.style_profile 整理为 LLM / WebUI 可消费的稳定结构。"""
    if not isinstance(style_profile, dict):
        return {
            "version": _SNAPSHOT_VERSION,
            "ready": False,
            "sample": None,
            "signals": None,
            "hints": ["尚无群风格画像"],
        }

    sample = style_profile.get("sample")
    raw = style_profile.get("raw")
    derived = style_profile.get("derived")
    ready = isinstance(derived, dict) and bool(derived)

    snapshot: dict[str, Any] = {
        "version": _SNAPSHOT_VERSION,
        "ready": ready,
        "updated_at": style_profile.get("updated_at"),
        "sample": sample if isinstance(sample, dict) else None,
        "signals": None,
        "hints": [],
    }

    if not ready:
        snapshot["hints"] = ["样本不足，暂不生成群风格"]
        return snapshot

    raw_dict = raw if isinstance(raw, dict) else {}
    affect_tone = raw_dict.get("affect_tone") if isinstance(raw_dict.get("affect_tone"), dict) else {}
    snapshot["signals"] = {
        "reply_bias_mul": derived.get("reply_bias_mul"),
        "speak_bias_mul": derived.get("speak_bias_mul"),
        "length_pref": derived.get("length_pref"),
        "chaos_bias": derived.get("chaos_bias"),
        "warmth_bias": derived.get("warmth_bias"),
        "assertiveness_bias": derived.get("assertiveness_bias"),
        "avg_plain_len": raw_dict.get("avg_plain_len"),
        "p50_plain_len": raw_dict.get("p50_plain_len"),
        "msgs_per_hour_active": raw_dict.get("msgs_per_hour_active"),
        "local_answer_ratio": raw_dict.get("local_answer_ratio"),
        "repeat_chain_rate": raw_dict.get("repeat_chain_rate"),
        "civility_score": affect_tone.get("civility_score"),
        "harsh_msg_ratio": affect_tone.get("harsh_msg_ratio"),
        "polite_msg_ratio": affect_tone.get("polite_msg_ratio"),
        "punct_aggression_avg": affect_tone.get("punct_aggression_avg"),
    }
    snapshot["hints"] = build_group_style_hints(snapshot["signals"])
    return snapshot


def build_group_style_hints(signals: dict[str, Any] | None) -> list[str]:
    if not isinstance(signals, dict):
        return []

    hints: list[str] = []
    length_pref = str(signals.get("length_pref") or "").strip()
    if length_pref == "short":
        hints.append("群消息偏短")
    elif length_pref == "long":
        hints.append("群消息偏长")
    elif length_pref == "medium":
        hints.append("群消息长度适中")

    msgs_per_hour = float(signals.get("msgs_per_hour_active") or 0.0)
    if msgs_per_hour >= 8:
        hints.append("聊天较活跃")
    elif 0 < msgs_per_hour < 3:
        hints.append("聊天较安静")

    chaos_bias = float(signals.get("chaos_bias") or 0.0)
    if chaos_bias >= 0.15:
        hints.append("复读链与短句常见")
    elif chaos_bias < 0.08:
        hints.append("接话句型较分散")

    reply_mul = float(signals.get("reply_bias_mul") or 1.0)
    if reply_mul >= 1.08:
        hints.append("适合更频繁接话")
    elif reply_mul <= 0.92:
        hints.append("适合更克制接话")

    civility = float(signals.get("civility_score") or 0.0)
    if civility >= 0.25:
        hints.append("群聊语气偏文明客气")
    elif civility <= -0.25:
        hints.append("群聊语气偏直接或有冲突用语")

    return hints


def compile_group_style_prompt(style_profile: dict[str, Any] | None, *, locale: str = "zh") -> str:
    """生成可嵌入 LLM system / memory 的群风格摘要。"""
    snapshot = compile_group_style_snapshot(style_profile)
    if locale != "zh":
        locale = "zh"

    if not snapshot["ready"]:
        body = "样本不足，暂无可用画像。"
        return wrap_stats_block("group_style", f"【群风格】{body}")

    signals = snapshot.get("signals") or {}
    hints = snapshot.get("hints") or []
    hint_text = "、".join(hints) if hints else "暂无显著特征"
    length_pref = normalize_enum(str(signals.get("length_pref") or ""), ALLOWED_LENGTH_PREFS, "unknown")

    body = (
        "【群风格】"
        f"长度偏好={length_pref}；"
        f"活跃={format_safe_decimal(signals.get('msgs_per_hour_active'), default='0', min_value=0)}条/活跃小时；"
        f"复读倾向={format_safe_decimal(signals.get('repeat_chain_rate'), default='0', min_value=0, max_value=1)}；"
        f"接话倍率={format_safe_decimal(signals.get('reply_bias_mul'), default='1', min_value=0, max_value=3)}；"
        f"主动发言倍率={format_safe_decimal(signals.get('speak_bias_mul'), default='1', min_value=0, max_value=3)}；"
        f"混沌={format_safe_decimal(signals.get('chaos_bias'), default='0', min_value=0, max_value=1)}。"
        f"摘要：{sanitize_prompt_literal(hint_text, max_len=256)}。"
    )
    return wrap_stats_block("group_style", body)
