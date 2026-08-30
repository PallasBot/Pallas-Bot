"""好感度 LLM 兜底定分：规则词表拿不准（含反讽）时交给模型。"""

from __future__ import annotations

import json
import re
from typing import Any

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.provider_client import complete_chat_message

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_AFFINITY_INPUT_MAX_LEN = 60
_AFFINITY_LLM_STEP = 0.4
_STABLE_NOTE_MAX_LEN = 48


async def score_affinity_with_llm(
    plain_text: str,
    *,
    task: str = "llm.relationship.affinity",
    cfg: LlmConfig | None = None,
) -> dict[str, Any] | None:
    """判断一句话对 bot 的好感倾向，返回 {affinity_delta, confidence, reason, stable_note}；失败或中性返回 None。"""
    c = cfg or get_llm_config()
    text = (plain_text or "").strip()[:_AFFINITY_INPUT_MAX_LEN]
    if not text:
        return None
    budget = task_token_budget(task)
    prompt = (
        "你正在判断群友对牛牛的好感倾向。注意反讽：比如「哇！好聪明」表面夸实际贬，"
        "「你还不感谢我」是命令式索取不算好感。"
        "只输出严格 JSON，不要任何多余文字："
        '{"affinity_delta": -0.4到0.4的浮点数（正为好感升高、负为下降，0为中性）, '
        '"confidence": 0到1的浮点数（你的把握）, "reason": 不超过40字的中文理由, '
        '"stable_note": 如能看出该用户的稳定特征（身份/习惯/偏好/相处方式），用不超过48字的第三人称事实句描述，'
        "仅凭这一句看不出来就填空字符串}"
        f"\n\n群友的话：{text}"
    )
    try:
        response = await complete_chat_message(
            [{"role": "user", "content": prompt}],
            model=str(c.llm_model or ""),
            options={"temperature": 0, "max_tokens": budget},
            cfg=c,
            task=task,
        )
    except Exception:
        return None
    raw = str(response.get("content") or "").strip()
    if not raw:
        return None
    match = _JSON_FENCE_RE.search(raw)
    body = (match.group(1) if match else raw).strip()
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        affinity_delta = float(data.get("affinity_delta"))
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        return None
    affinity_delta = round(max(-_AFFINITY_LLM_STEP, min(_AFFINITY_LLM_STEP, affinity_delta)), 3)
    confidence = round(max(0.0, min(1.0, confidence)), 3)
    reason = str(data.get("reason") or "")[:40]
    note = " ".join(str(data.get("stable_note") or "").split())[:_STABLE_NOTE_MAX_LEN]
    if affinity_delta == 0.0:
        return None
    return {
        "affinity_delta": affinity_delta,
        "confidence": confidence,
        "reason": reason,
        "stable_note": note,
    }
