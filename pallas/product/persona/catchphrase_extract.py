"""从 Bot 成功回复中抽取短口癖候选（语气习惯，非整句接话）。"""

from __future__ import annotations

import json
import re
from typing import Any

# 口癖：短、可复用；整句接话 / 多意图枚举不应入库
_HABIT_MIN = 2
_HABIT_MAX = 12
_LISTING_RE = re.compile(r"[，、；;]|以及|或者|还有")
_ENUM_HEAVY_RE = re.compile(r"[、；;]|以及|或者")
_SENTENCE_END_RE = re.compile(r"[。！？!?…]")
_OFFER_RE = re.compile(
    r"(能聊|接接|开开玩|帮你|要不要|可以吗|需不需要|找我玩|陪你|随时|尽管说|就行)",
)
# 自称梗：我 + 拉丁昵称（如我chovy）；不用 \w，避免吞掉后续中文
_SELF_TAG_RE = re.compile(r"(我[A-Za-z][A-Za-z0-9_]{0,11})")
_LAUGH_PREFIX_RE = re.compile(r"^(?:哈{2,}|嘿+|呵{2,})")
_PARTICLE_TAIL_RE = re.compile(
    r"^[\u4e00-\u9fffA-Za-z]{1,8}(?:捏|啦|呗|喔|哦|嘿|哈|呀|哟|咧|哒)$",
)


def clean_catchphrase_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def is_catchphrase_habit(saying: str) -> bool:
    """是否像可反复带上的短口癖，而非完整接话。"""
    plain = clean_catchphrase_text(saying)
    if not _HABIT_MIN <= len(plain) <= _HABIT_MAX:
        return False
    if "[cq:" in plain.lower():
        return False
    if _LISTING_RE.search(plain):
        return False
    if _OFFER_RE.search(plain):
        return False
    if len(_SENTENCE_END_RE.findall(plain)) >= 1 and len(plain) > 8:
        return False
    if plain.count("，") + plain.count(",") >= 1:
        return False
    # 带「我」时仅接受拉丁自称梗，避免「我玩就行」一类碎片
    if "我" in plain and not _SELF_TAG_RE.fullmatch(plain):
        return False
    return True


def _occasion_for(saying: str) -> str:
    if _SELF_TAG_RE.fullmatch(saying):
        return "自称梗"
    if _PARTICLE_TAIL_RE.match(saying):
        return "语气尾巴"
    return "口头禅"


def extract_catchphrase_candidates(text: str, *, limit: int = 3) -> list[tuple[str, str]]:
    """规则抽取：优先自称梗 / 短口头禅；能力罗列句不切碎片。"""
    plain = clean_catchphrase_text(text)
    if not plain:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        saying = clean_catchphrase_text(raw)
        saying = _LAUGH_PREFIX_RE.sub("", saying).strip()
        if not is_catchphrase_habit(saying) or saying in seen:
            return
        seen.add(saying)
        out.append((saying, _occasion_for(saying)))

    for match in _SELF_TAG_RE.finditer(plain):
        add(match.group(1))
        if len(out) >= limit:
            return out[:limit]

    # 顿号/「以及」罗列多为能力介绍，只保留自称梗
    if _ENUM_HEAVY_RE.search(plain):
        return out[:limit]

    for part in re.split(r"[，,。！？!?;；\s]+", plain):
        add(part)
        if len(out) >= limit:
            return out[:limit]

    if is_catchphrase_habit(plain):
        add(plain)

    return out[:limit]


def parse_llm_catchphrase_payload(raw: str) -> list[tuple[str, str]]:
    """解析 LLM 返回的 JSON：{\"items\":[{\"saying\":\"我chovy\",\"occasion\":\"自称梗\"}]}。"""
    text = str(raw or "").strip()
    if not text:
        return []
    payload: Any = None
    try:
        from pallas.product.llm.memory.graph.json_parse import parse_llm_json

        payload = parse_llm_json(text)
    except Exception:
        try:
            start = text.find("{")
            end = text.rfind("}")
            payload = json.loads(text[start : end + 1]) if start >= 0 and end > start else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        saying = clean_catchphrase_text(str(item.get("saying") or ""))
        if not is_catchphrase_habit(saying) or saying in seen:
            continue
        occasion = clean_catchphrase_text(str(item.get("occasion") or "")) or _occasion_for(saying)
        seen.add(saying)
        out.append((saying, occasion[:20]))
    return out


_EXTRACT_SYSTEM = (
    "你从机器人成功回复里抽取账号口癖候选。"
    "口癖是短、可反复自然带上的语气习惯或自称梗（如「我chovy」「那很牛了」「好耶」），"
    "不是完整接话、不是能力介绍、不是多逗号并列。"
    '只输出 JSON：{"items":[{"saying":"...","occasion":"自称梗|口头禅|语气尾巴"}]}'
    '最多 3 条；没有则 {"items":[]}。'
)


def _resolve_extract_task_and_model() -> tuple[str, str]:
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.providers_store import resolve_endpoint_for_task

    cfg = get_llm_config()
    for task in ("llm_chat",):
        endpoint = resolve_endpoint_for_task(task)
        if endpoint is not None and endpoint.model:
            return task, endpoint.model
    return "llm_chat", str(cfg.llm_model or "").strip()


async def extract_catchphrase_candidates_llm(text: str, *, limit: int = 3) -> list[tuple[str, str]]:
    """可选 LLM 抽取；失败返回空，由规则路径兜底。"""
    plain = clean_catchphrase_text(text)
    if len(plain) < 4:
        return []
    from pallas.product.llm.provider_client import complete_chat_message

    task, model = _resolve_extract_task_and_model()
    if not model:
        return []
    message = await complete_chat_message(
        [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": f"回复：\n{plain[:500]}"},
        ],
        model=model,
        options={"temperature": 0.1, "num_predict": 200},
        task=task,
    )
    items = parse_llm_catchphrase_payload(str(message.get("content") or ""))
    return items[: max(0, int(limit))]
