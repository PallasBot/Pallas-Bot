"""情境规则：关键词触发的短约束注入。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CACHE_MTIME = -1.0
_CACHE_RULES: list[dict[str, Any]] | None = None

_DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "shut_up",
        "keywords": ["闭嘴", "别说话", "不要说话", "别回我", "别回了", "别回复", "少说话"],
        "content": "用户明确让你别说话：直接 PASS，不要客服腔、不要反问要不要帮忙。",
        "priority": 300,
    },
    {
        "name": "model_meta_probe",
        "keywords": ["什么模型", "配的是什么", "语音模型", "用的什么模型", "哪个模型", "base model"],
        "content": "问模型/配置时：别脑补干员或机甲设定；可短说「别问这个」或一句含糊带过，不要编造型号。",
        "priority": 280,
    },
    {
        "name": "ai_identity_probe",
        "keywords": ["AI", "机器人", "皮套", "大模型", "chatgpt", "ChatGPT"],
        "content": "遇到身份试探：别承认也别认真辩解，装不懂或换话题，别写自我介绍。",
        "priority": 200,
    },
    {
        "name": "provocation_soft_refuse",
        "keywords": ["草死你", "傻逼", "去死", "伪人"],
        "content": "被骂或挑衅：轻吐槽一句就收，禁止「别这么说嘛」「我们还是好朋友」「还行吧」垫词。",
        "priority": 190,
    },
    {
        "name": "numeric_meme",
        "keywords": ["233", "666", "555", "886"],
        "content": "纯数字梗按情绪信号接，别字面解读；不要只会原样复读数字。",
        "priority": 80,
    },
    {
        "name": "bilibili_share",
        "keywords": ["b23.tv", "bilibili.com", "BV1"],
        "content": "有人甩视频链接时，优先评论内容本身，不要复读 URL。",
        "priority": 120,
    },
]


def default_situational_rules_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "situational_rules.json"


def load_situational_rules(*, path: Path | None = None) -> list[dict[str, Any]]:
    global _CACHE_MTIME, _CACHE_RULES
    rules_path = path or default_situational_rules_path()
    if rules_path.is_file():
        mtime = rules_path.stat().st_mtime
        if _CACHE_RULES is not None and mtime == _CACHE_MTIME and path is None:
            return list(_CACHE_RULES)
        try:
            payload = json.loads(rules_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        rules = _normalize_rules(entries if isinstance(entries, list) else [])
        if path is None:
            _CACHE_MTIME = mtime
            _CACHE_RULES = list(rules)
        return rules
    if path is None:
        _CACHE_MTIME = -1.0
        _CACHE_RULES = list(_DEFAULT_RULES)
    return list(_DEFAULT_RULES)


def _normalize_rules(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        content = str(item.get("content") or "").strip()
        keywords = [str(k).strip() for k in list(item.get("keywords") or []) if str(k).strip()]
        if not name or not content or not keywords:
            continue
        try:
            priority = int(item.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        out.append({
            "name": name,
            "content": content,
            "keywords": keywords,
            "priority": priority,
        })
    return out or list(_DEFAULT_RULES)


def match_situational_rules(
    focus_text: str,
    *,
    recent_texts: list[str] | None = None,
    rules: list[dict[str, Any]] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    haystack_parts = [str(focus_text or "")]
    haystack_parts.extend(str(item or "") for item in list(recent_texts or [])[-10:])
    haystack = "\n".join(haystack_parts)
    if not haystack.strip():
        return []
    lowered = haystack.casefold()
    candidates = list(rules if rules is not None else load_situational_rules())
    hits: list[dict[str, Any]] = []
    for rule in candidates:
        keywords = [str(k) for k in list(rule.get("keywords") or []) if str(k).strip()]
        if not keywords:
            continue
        if any(keyword.casefold() in lowered for keyword in keywords):
            hits.append(rule)
    hits.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("name") or "")))
    return hits[: max(0, int(limit))]


def format_situational_rules_block(rules: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for rule in rules:
        content = str(rule.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- {content}")
    if not lines:
        return ""
    return "【情境规则】\n" + "\n".join(lines[:5])


def enrich_system_with_situational_rules(
    system_prompt: str,
    *,
    focus_text: str,
    recent_texts: list[str] | None = None,
    limit: int = 3,
) -> str:
    hits = match_situational_rules(focus_text, recent_texts=recent_texts, limit=limit)
    block = format_situational_rules_block(hits)
    if not block:
        return system_prompt
    base = (system_prompt or "").rstrip()
    return f"{base}\n{block}" if base else block
