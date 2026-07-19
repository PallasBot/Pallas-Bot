"""调用 AI 仓 persona affect-refine 端点。"""

from __future__ import annotations

from typing import Any

from nonebot import logger

from pallas.core.shared.utils import HTTPXClient
from pallas.product.llm.config import get_llm_config, llm_server_base_url

from .compile_group_style import compile_group_style_snapshot

_DEFAULT_ENDPOINT = "/api/persona/affect-refine"
_DEFAULT_TIMEOUT_SEC = 25.0
_SAMPLE_MAX_LEN = 120
_SAMPLE_LIMIT = 12


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


def affect_refine_endpoint_path() -> str:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("LLM_AFFECT_REFINE_ENDPOINT")
    if raw is None or not raw.strip():
        return _DEFAULT_ENDPOINT
    path = raw.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def affect_refine_timeout_sec() -> float:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("LLM_AFFECT_REFINE_TIMEOUT_SEC")
    if raw is None:
        return _DEFAULT_TIMEOUT_SEC
    try:
        return max(1.0, float(raw.strip()))
    except ValueError:
        return _DEFAULT_TIMEOUT_SEC


async def post_affect_refine(payload: dict[str, Any]) -> dict[str, Any] | None:
    cfg = get_llm_config()
    base = llm_server_base_url(cfg)
    url = f"{base}{affect_refine_endpoint_path()}"
    timeout = affect_refine_timeout_sec()
    try:
        response = await HTTPXClient.post(url, json=payload, timeout=timeout)
    except Exception:
        logger.warning("affect refine request failed: url={}", url)
        return None
    if not response:
        return None
    try:
        body = response.json()
    except Exception:
        logger.warning("affect refine invalid json: url={}", url)
        return None
    if not isinstance(body, dict):
        return None
    if body.get("error"):
        logger.warning("affect refine error response: {}", body.get("error"))
        return None
    return body
