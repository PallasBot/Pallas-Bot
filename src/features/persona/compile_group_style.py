from __future__ import annotations

from typing import Any

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
    snapshot["signals"] = {
        "reply_bias_mul": derived.get("reply_bias_mul"),
        "speak_bias_mul": derived.get("speak_bias_mul"),
        "length_pref": derived.get("length_pref"),
        "chaos_bias": derived.get("chaos_bias"),
        "avg_plain_len": raw_dict.get("avg_plain_len"),
        "p50_plain_len": raw_dict.get("p50_plain_len"),
        "msgs_per_hour_active": raw_dict.get("msgs_per_hour_active"),
        "local_answer_ratio": raw_dict.get("local_answer_ratio"),
        "repeat_chain_rate": raw_dict.get("repeat_chain_rate"),
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

    return hints


def compile_group_style_prompt(style_profile: dict[str, Any] | None, *, locale: str = "zh") -> str:
    """生成可嵌入 LLM system / memory 的群风格摘要。"""
    snapshot = compile_group_style_snapshot(style_profile)
    if locale != "zh":
        locale = "zh"

    if not snapshot["ready"]:
        return "【群风格】样本不足，暂无可用画像。"

    signals = snapshot.get("signals") or {}
    hints = snapshot.get("hints") or []
    hint_text = "、".join(hints) if hints else "暂无显著特征"

    return (
        "【群风格】"
        f"长度偏好={signals.get('length_pref') or 'unknown'}；"
        f"活跃={signals.get('msgs_per_hour_active')}条/活跃小时；"
        f"复读倾向={signals.get('repeat_chain_rate')}；"
        f"接话倍率={signals.get('reply_bias_mul')}；"
        f"主动发言倍率={signals.get('speak_bias_mul')}；"
        f"混沌={signals.get('chaos_bias')}。"
        f"摘要：{hint_text}。"
    )
