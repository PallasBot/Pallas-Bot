"""回复效果窄维度评审：启发式打分 + 可选落盘。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SERVICE_PHRASES = ("有什么可以帮", "为您服务", "希望对你有帮助", "请问", "您好")
_OVER_EAGER = ("继续聊", "换个话题", "有事叫我", "聊聊吗")


def default_reply_effect_path() -> Path:
    import os

    from pallas.core.foundation.paths import plugin_data_dir

    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir) / "llm"
        root.mkdir(parents=True, exist_ok=True)
        return root / "reply_effect_eval.jsonl"
    path = plugin_data_dir("pb_webui", create=True) / "llm"
    path.mkdir(parents=True, exist_ok=True)
    return path / "reply_effect_eval.jsonl"


def heuristic_reply_effect_scores(reply_text: str) -> dict[str, int]:
    text = str(reply_text or "").strip()
    social = 3
    warmth = 3
    competence = 3
    appropriateness = 3
    uncanny = 2
    if not text:
        return {
            "social_presence": 1,
            "warmth": 1,
            "competence": 1,
            "appropriateness": 1,
            "uncanny_risk": 5,
        }
    if any(p in text for p in _SERVICE_PHRASES):
        uncanny = 5
        appropriateness = 2
        social = 2
    if any(p in text for p in _OVER_EAGER):
        uncanny = max(uncanny, 4)
        appropriateness = min(appropriateness, 2)
    if len(text) <= 24:
        social = max(social, 4)
        warmth = max(warmth, 3)
    if len(text) > 80:
        uncanny = max(uncanny, 4)
        appropriateness = min(appropriateness, 2)
    if "？" in text or "?" in text:
        competence = max(competence, 3)
    return {
        "social_presence": social,
        "warmth": warmth,
        "competence": competence,
        "appropriateness": appropriateness,
        "uncanny_risk": uncanny,
    }


def build_reply_effect_prompt(reply_text: str, *, followups: list[str] | None = None) -> str:
    follow_lines = "\n".join(f"- {item}" for item in list(followups or [])[:6]) or "（暂无）"
    return (
        "请只输出 JSON，对这条 bot 回复做窄维度评分（1-5）。\n"
        "字段：social_presence / warmth / competence / appropriateness / uncanny_risk。\n"
        "uncanny_risk：1=自然，5=过度拟人/油腻/客服腔。\n\n"
        f"bot 回复：\n{str(reply_text or '').strip()[:1200]}\n\n"
        f"后续用户消息：\n{follow_lines}\n"
    )


def parse_reply_effect_scores(raw: str) -> dict[str, int]:
    text = str(raw or "").strip()
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start >= 0:
            try:
                data, _ = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return heuristic_reply_effect_scores("")
    out: dict[str, int] = {}
    for key in ("social_presence", "warmth", "competence", "appropriateness", "uncanny_risk"):
        raw_item = data.get(key)
        if isinstance(raw_item, dict):
            value = raw_item.get("score")
        else:
            value = raw_item
        try:
            score = int(float(value))
        except (TypeError, ValueError):
            score = 3
        out[key] = max(1, min(5, score))
    return out


def append_reply_effect_record(record: dict[str, Any], *, path: Path | None = None) -> Path:
    target = Path(path) if path is not None else default_reply_effect_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("created_at", int(time.time()))
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def evaluate_and_record_reply_effect(
    reply_text: str,
    *,
    task_type: str = "",
    group_id: int | None = None,
    user_id: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    scores = heuristic_reply_effect_scores(reply_text)
    record = {
        "task_type": str(task_type or ""),
        "group_id": group_id,
        "user_id": user_id,
        "reply_text": str(reply_text or "").strip()[:500],
        "scores": scores,
        "source": "heuristic",
    }
    append_reply_effect_record(record, path=path)
    return record
