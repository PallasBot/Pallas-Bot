"""群情感 refine：经 Bot 内核 LLM 完成（失败回退启发式）。"""

from __future__ import annotations

import json
import re
from typing import Any

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

from .compile_group_style import compile_group_style_snapshot

_DEFAULT_TIMEOUT_SEC = 25.0
_SAMPLE_MAX_LEN = 120
_SAMPLE_LIMIT = 12
_DELTA_CLAMP = 0.5
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")
_SYSTEM_PROMPT = (
    "你是群聊语气分析助手。根据统计与脱敏样本，输出 JSON："
    '{"warmth_delta": number, "assertiveness_delta": number, '
    '"confidence": number, "summary": string, "triggers": []}。'
    "不要输出 markdown 或解释文字。"
)


def collect_affect_refine_samples(messages: list[Any], *, limit: int = _SAMPLE_LIMIT) -> list[str]:
    samples: list[str] = []
    for message in messages:
        plain = str(getattr(message, "plain_text", "") or "").strip()
        if not plain:
            continue
        if len(plain) > _SAMPLE_MAX_LEN:
            plain = plain[: _SAMPLE_MAX_LEN - 1] + "…"
        samples.append(plain)
        if len(samples) >= limit:
            break
    return samples


def build_affect_refine_payload(
    profile: dict[str, Any],
    *,
    group_id: int,
    message_samples: list[str] | None = None,
) -> dict[str, Any]:
    snapshot = compile_group_style_snapshot(profile)
    hints = snapshot.get("hints") if isinstance(snapshot.get("hints"), list) else []
    sample = profile.get("sample") if isinstance(profile.get("sample"), dict) else {}
    raw = profile.get("raw") if isinstance(profile.get("raw"), dict) else {}
    derived = profile.get("derived") if isinstance(profile.get("derived"), dict) else {}

    payload_profile: dict[str, Any] = {}
    if sample:
        payload_profile["sample"] = {
            "message_count": sample.get("message_count"),
            "answer_count": sample.get("answer_count"),
            "window_hours": sample.get("window_hours"),
        }
    if raw or derived:
        payload_profile["raw"] = {
            "repeat_chain_rate": raw.get("repeat_chain_rate"),
            "local_answer_ratio": raw.get("local_answer_ratio"),
            "affect_tone": raw.get("affect_tone"),
        }
        payload_profile["derived"] = {
            "warmth_bias": derived.get("warmth_bias"),
            "assertiveness_bias": derived.get("assertiveness_bias"),
            "length_pref": derived.get("length_pref"),
            "chaos_bias": derived.get("chaos_bias"),
        }

    return {
        "group_id": int(group_id),
        "profile": payload_profile,
        "hints": [str(item) for item in hints if str(item).strip()],
        "message_samples": list(message_samples or [])[:_SAMPLE_LIMIT],
    }


def affect_refine_timeout_sec() -> float:
    raw = repo_env_raw_value("LLM_AFFECT_REFINE_TIMEOUT_SEC")
    if raw is None:
        return _DEFAULT_TIMEOUT_SEC
    try:
        return max(1.0, float(raw.strip()))
    except ValueError:
        return _DEFAULT_TIMEOUT_SEC


def clamp_delta(value: float) -> float:
    return max(-_DELTA_CLAMP, min(_DELTA_CLAMP, float(value)))


def build_affect_refine_user_prompt(payload: dict[str, Any]) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    derived = profile.get("derived") if isinstance(profile.get("derived"), dict) else {}
    raw = profile.get("raw") if isinstance(profile.get("raw"), dict) else {}
    tone = raw.get("affect_tone") if isinstance(raw.get("affect_tone"), dict) else {}
    hints = [str(item).strip() for item in (payload.get("hints") or []) if str(item).strip()]
    samples = [str(item).strip() for item in (payload.get("message_samples") or []) if str(item).strip()]

    lines = [
        "请根据群聊统计与样本，在已有 warmth/assertiveness 基线之上给出小幅情感偏移。",
        "只输出 JSON 对象，字段：warmth_delta, assertiveness_delta, confidence, summary, triggers。",
        "triggers 可为空数组；|delta| 通常不超过 0.15。",
        "",
        f"group_id={payload.get('group_id')}",
    ]
    if derived:
        lines.append(
            "derived: "
            f"warmth_bias={derived.get('warmth_bias')}, assertiveness_bias={derived.get('assertiveness_bias')}, "
            f"length_pref={derived.get('length_pref')}, chaos_bias={derived.get('chaos_bias')}"
        )
    if raw:
        lines.append(
            f"raw: repeat_chain_rate={raw.get('repeat_chain_rate')}, local_answer_ratio={raw.get('local_answer_ratio')}"
        )
    if tone:
        lines.append(
            "affect_tone: "
            f"civility={tone.get('civility_score')}, harsh_ratio={tone.get('harsh_msg_ratio')}, "
            f"polite_ratio={tone.get('polite_msg_ratio')}, punct={tone.get('punct_aggression_avg')}"
        )
    if hints:
        lines.append("hints: " + "；".join(hints[:8]))
    if samples:
        lines.append("message_samples:")
        lines.extend(f"- {item}" for item in samples[:_SAMPLE_LIMIT])
    return "\n".join(lines)


def parse_affect_refine_json(text: str) -> dict[str, Any]:
    body = str(text or "").strip()
    if not body:
        raise ValueError("empty model output")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(body)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


def normalize_affect_refine_llm_body(data: dict[str, Any]) -> dict[str, Any]:
    triggers: list[dict[str, Any]] = []
    raw_triggers = data.get("triggers")
    if isinstance(raw_triggers, list):
        for item in raw_triggers[:8]:
            if not isinstance(item, dict):
                continue
            phrase = str(item.get("phrase") or "").strip()
            if not phrase:
                continue
            triggers.append({
                "phrase": phrase[:64],
                "warmth_delta": clamp_delta(float(item.get("warmth_delta") or 0.0)),
                "assertiveness_delta": clamp_delta(float(item.get("assertiveness_delta") or 0.0)),
                "ttl_hours": int(item.get("ttl_hours") or 168),
            })
    summary = str(data.get("summary") or "").strip()
    if len(summary) > 256:
        summary = summary[:255] + "…"
    out: dict[str, Any] = {
        "warmth_delta": clamp_delta(float(data.get("warmth_delta") or 0.0)),
        "assertiveness_delta": clamp_delta(float(data.get("assertiveness_delta") or 0.0)),
        "confidence": max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
        "summary": summary,
    }
    if triggers:
        out["triggers"] = triggers
    return out


async def post_affect_refine(payload: dict[str, Any]) -> dict[str, Any] | None:
    """经 Bot 内核 provider 完成 refine；失败返回 None 由上层走启发式。"""
    from pallas.product.llm.provider_client import LlmProviderError, complete_chat_message

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": build_affect_refine_user_prompt(payload)},
    ]
    try:
        message = await complete_chat_message(
            messages,
            model="",
            options={"temperature": 0.3, "max_tokens": 512},
            task="affect_refine",
        )
    except LlmProviderError as exc:
        logger.warning("affect refine kernel failed: {}", exc)
        return None
    except Exception:
        logger.warning("affect refine kernel request failed")
        return None
    content = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
    if not content:
        return None
    try:
        parsed = parse_affect_refine_json(content)
        return normalize_affect_refine_llm_body(parsed)
    except Exception as exc:
        logger.warning("affect refine parse failed: {}", exc)
        return None
