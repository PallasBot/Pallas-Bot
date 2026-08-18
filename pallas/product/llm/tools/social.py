"""群内社交工具：查询主人/群成员，生成受控提及令牌。

隐私规则：只有主人与 bot 同群时才返回主人身份；不在群时不透露任何身份信息。
LLM 回复中写 ``[[@key]]`` 占位符，发送前由 delivery 校验授权后替换为 CQ at。
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.logging import log_rate_limited
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

try:
    from nonebot import logger
except Exception:  # pragma: no cover - 测试环境无 nonebot 时兜底
    import logging

    logger = logging.getLogger("pallas.social")

_MENTION_GRANT_TTL_SEC = 300.0
_MEMBER_CACHE_TTL_SEC = 30.0
# 提及占位符：LLM 可能输出单/双括号或裸 @key；带括号的未授权项会被删除
_MENTION_PLACEHOLDER_RE = re.compile(r"(?:\[{1,2}|【|（|\(|「)?\s*@([^\s\]】）)」]+)\s*(?:\]{1,2}|】|）|\)|」)?")
_CQ_SEGMENT_RE = re.compile(r"\[CQ:[^\]]*\]", re.IGNORECASE)
_DISPLAY_CONTROL_RE = re.compile(r"[\[\]【】（）()@]")

_grants_lock = threading.Lock()
_grants: dict[tuple[int, int, str], dict[str, tuple[int, float]]] = {}
_social_requests: dict[tuple[int, int, str], float] = {}
_member_cache_lock = threading.Lock()
_member_cache: dict[tuple[int, int], tuple[float, tuple[dict[str, Any], ...]]] = {}


def clear_social_mention_state() -> None:
    with _grants_lock:
        _grants.clear()
        _social_requests.clear()
    with _member_cache_lock:
        _member_cache.clear()


def grant_mention(
    bot_id: int,
    group_id: int,
    request_id: str,
    token_kind: str,
    qq: int,
    *,
    ttl_sec: float = _MENTION_GRANT_TTL_SEC,
) -> str:
    request = str(request_id or "").strip()
    kind = str(token_kind or "").strip()
    if not request or kind not in {"master", "member"}:
        return ""
    with _grants_lock:
        _prune_grants_locked(time.time())
        bucket = _grants.setdefault((int(bot_id), int(group_id), request), {})
        index = 0
        while f"{kind}_{index}" in bucket:
            index += 1
        key = f"{kind}_{index}"
        bucket[key] = (int(qq), time.time() + max(1.0, float(ttl_sec)))
    return key


def mark_social_request(bot_id: int, group_id: int, request_id: str) -> None:
    request = str(request_id or "").strip()
    if not request:
        return
    with _grants_lock:
        now = time.time()
        _prune_grants_locked(now)
        _social_requests[(int(bot_id), int(group_id), request)] = now + _MENTION_GRANT_TTL_SEC


def resolve_mention_qq(bot_id: int, group_id: int, request_id: str, key: str) -> int | None:
    request = str(request_id or "").strip()
    k = str(key or "").strip()
    if not request or not k:
        return None
    now = time.time()
    with _grants_lock:
        _prune_grants_locked(now)
        bucket = _grants.get((int(bot_id), int(group_id), request))
        if not bucket:
            return None
        entry = bucket.get(k)
        if entry is None or entry[1] <= now:
            bucket.pop(k, None)
            return None
        return entry[0]


def replace_mention_tokens(text: str, *, bot_id: int, group_id: int, request_id: str) -> str:
    """把已授权的提及占位符替换为 CQ at；带括号的未授权项删除，裸 @ 保留。"""

    def repl(match: re.Match[str]) -> str:
        qq = resolve_mention_qq(bot_id, group_id, request_id, match.group(1))
        if qq is not None:
            return f"[CQ:at,qq={qq}]"
        raw = match.group(0)
        return raw if raw.startswith("@") else ""

    return _MENTION_PLACEHOLDER_RE.sub(repl, str(text or ""))


def _prune_grants_locked(now: float) -> None:
    for scope, bucket in tuple(_grants.items()):
        expired = [key for key, (_, expires_at) in bucket.items() if expires_at <= now]
        for key in expired:
            bucket.pop(key, None)
        if not bucket:
            _grants.pop(scope, None)
    for scope, expires_at in tuple(_social_requests.items()):
        if expires_at <= now:
            _social_requests.pop(scope, None)


def is_social_request(bot_id: int, group_id: int, request_id: str) -> bool:
    request = str(request_id or "").strip()
    if not request:
        return False
    with _grants_lock:
        _prune_grants_locked(time.time())
        return (int(bot_id), int(group_id), request) in _social_requests


def parse_superuser_ids() -> list[int]:
    raw = str(repo_env_raw_value("SUPERUSERS") or os.environ.get("SUPERUSERS") or "").strip()
    if not raw:
        return []
    try:
        import json

        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [int(item) for item in parsed if str(item or "").strip().isdigit()]
    except (ValueError, TypeError):
        pass
    return [int(part.strip()) for part in re.split(r"[,，\s]+", raw) if part.strip().isdigit()]


def runtime_superuser_ids() -> list[int]:
    try:
        from nonebot import get_driver

        return [int(item) for item in get_driver().config.superusers if str(item).strip().isdigit()]
    except Exception:
        return []


async def resolve_master_user_ids(bot_id: int) -> list[int]:
    ids: set[int] = set(parse_superuser_ids()) | set(runtime_superuser_ids())
    try:
        from pallas.core.foundation.config import get_bot_admins

        ids.update(int(item) for item in await get_bot_admins(int(bot_id)))
    except Exception:
        pass
    return sorted(ids)


async def _bot_for(bot_id: int):
    from nonebot import get_bots

    return get_bots().get(str(int(bot_id)))


async def _member_display_name(bot, group_id: int, qq: int) -> str | None:
    try:
        info = await bot.get_group_member_info(group_id=int(group_id), user_id=int(qq))
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    for raw_name in (info.get("card"), info.get("nickname")):
        cleaned = sanitize_social_display_name(raw_name)
        if cleaned:
            return cleaned
    return None


def sanitize_social_display_name(raw_name: object) -> str:
    text = _CQ_SEGMENT_RE.sub("", str(raw_name or ""))
    text = _DISPLAY_CONTROL_RE.sub("", text)
    return sanitize_prompt_literal(text, max_len=80)


def social_display_name_from_row(row: dict[str, Any]) -> str:
    return sanitize_social_display_name(row.get("card")) or sanitize_social_display_name(row.get("nickname"))


def social_member_match_score(name: str, folded_query: str) -> int | None:
    folded = str(name or "").casefold()
    if folded == folded_query:
        return 0
    if folded_query in folded:
        return 1
    if folded in folded_query:
        return 2
    return None


async def _group_member_rows(bot, group_id: int) -> list[dict[str, Any]]:
    try:
        data = await bot.get_group_member_list(group_id=int(group_id))
    except Exception:
        return []
    return list(data) if isinstance(data, list) else []


async def cached_group_member_rows(bot, bot_id: int, group_id: int) -> list[dict[str, Any]]:
    key = (int(bot_id), int(group_id))
    now = time.time()
    with _member_cache_lock:
        cached = _member_cache.get(key)
        if cached is not None and cached[0] > now:
            return [dict(row) for row in cached[1]]
    rows = await _group_member_rows(bot, group_id)
    if not rows:
        return []
    snapshot = tuple(dict(row) for row in rows)
    with _member_cache_lock:
        _member_cache[key] = (now + _MEMBER_CACHE_TTL_SEC, snapshot)
    return [dict(row) for row in snapshot]


def register_social_tools() -> None:
    base = frozenset({ToolCapability.REQUIRES_GROUP_CONTEXT.value})
    register_tool(
        LlmToolSpec(
            name="social.master.info",
            description=(
                "查询「主人」（运营者/管理员）是否在本群。仅在主人在本群时返回其信息与提及令牌；"
                "主人不在本群时只返回 in_group=false，不得透露主人身份、QQ 或任何线索。"
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            domains=frozenset({"social", "chat"}),
            handler=handle_master_info,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}) | base,
            visibility="deferred",
            hints=frozenset({"你主人", "@主人", "叫主人", "主人出来", "喊主人", "主人的"}),
            estimated_duration_ms=600,
            display_mode="detail",
        )
    )
    register_tool(
        LlmToolSpec(
            name="social.member.find",
            description="按群名片或昵称在本群查找成员，返回匹配到的成员与提及令牌；找不到就如实说找不到。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "成员昵称或群名片关键词"}},
                "required": ["query"],
            },
            domains=frozenset({"social", "chat"}),
            handler=handle_member_find,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}) | base,
            visibility="deferred",
            hints=frozenset({"群里有没有", "有没有人叫", "找一下", "喊一下", "@一下", "叫一下", "是谁在群里"}),
            estimated_duration_ms=600,
            display_mode="detail",
        )
    )


async def handle_master_info(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del arguments
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    if not context.request_id:
        return {"ok": False, "error": "request_context_required"}
    mark_social_request(context.bot_id, context.group_id, context.request_id)
    bot = await _bot_for(context.bot_id)
    if bot is None:
        return {"ok": False, "error": "bot_unavailable"}
    masters: list[dict[str, Any]] = []
    for qq in await resolve_master_user_ids(context.bot_id):
        name = await _member_display_name(bot, context.group_id, qq)
        if name is None:
            continue
        key = grant_mention(context.bot_id, context.group_id, context.request_id, "master", qq)
        masters.append({"key": key, "name": name})
    if not masters:
        log_rate_limited(
            logger,
            "info",
            "llm.social.master_lookup",
            "social master lookup completed with no in-group owner",
        )
        return {
            "ok": True,
            "result": {"summary": "owner lookup completed", "master_in_group": False, "masters": []},
            "summary": "主人不在本群，不要透露主人身份或 QQ，如实说主人不在这个群。",
        }
    log_rate_limited(
        logger,
        "info",
        "llm.social.master_lookup",
        "social master lookup completed with [{}] in-group owner(s)",
        len(masters),
    )
    return {
        "ok": True,
        "result": {
            "summary": "owner lookup completed",
            "master_in_group": True,
            "master_names": [item["name"] for item in masters],
            "masters": masters,
            "hint": "想 @ 主人时在回复中写对应的 [[@key]]（如 [[@master_0]]），不想 @ 就只提名字。",
        },
    }


async def handle_member_find(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    if not context.request_id:
        return {"ok": False, "error": "request_context_required"}
    mark_social_request(context.bot_id, context.group_id, context.request_id)
    query = str((arguments or {}).get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}
    bot = await _bot_for(context.bot_id)
    if bot is None:
        return {"ok": False, "error": "bot_unavailable"}
    members = await cached_group_member_rows(bot, context.bot_id, context.group_id)
    scored: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    folded_query = query.casefold()
    for row in members:
        qq = row.get("user_id")
        if qq is None or int(qq) in seen:
            continue
        qq_int = int(qq)
        name = social_display_name_from_row(row)
        if not name:
            continue
        score = social_member_match_score(name, folded_query)
        if score is None:
            continue
        seen.add(qq_int)
        scored.append((score, qq_int, name))
    scored.sort(key=lambda item: (item[0], len(item[2])))
    matches: list[dict[str, Any]] = []
    for _score, qq, _name in scored[:5]:
        name = await _member_display_name(bot, context.group_id, qq)
        if name is None or social_member_match_score(name, folded_query) is None:
            continue
        key = grant_mention(context.bot_id, context.group_id, context.request_id, "member", qq)
        matches.append({"key": key, "name": name})
    if not matches:
        log_rate_limited(logger, "info", "llm.social.member_find", "social member lookup completed with no match")
        return {
            "ok": True,
            "result": {"summary": "member lookup completed", "matches": []},
            "summary": "没找到匹配的群成员，如实说找不到，不要编造。",
        }
    log_rate_limited(
        logger,
        "info",
        "llm.social.member_find",
        "social member lookup completed with [{}] match(es)",
        len(matches),
    )
    return {
        "ok": True,
        "result": {
            "summary": "member lookup completed",
            "matches": matches,
            "member_names": [item["name"] for item in matches],
            "hint": "想 @ 某成员时在回复中写对应的 [[@key]]（如 [[@member_0]]），不想 @ 就只提名字。",
        },
    }
