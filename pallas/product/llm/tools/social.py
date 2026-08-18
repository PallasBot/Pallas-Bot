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
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

try:
    from nonebot import logger
except Exception:  # pragma: no cover - 测试环境无 nonebot 时兜底
    import logging

    logger = logging.getLogger("pallas.social")

_MENTION_GRANT_TTL_SEC = 300.0
# 提及占位符：LLM 可能输出单/双括号或裸 @key；带括号的未授权项会被删除
_MENTION_PLACEHOLDER_RE = re.compile(r"(?:\[{1,2}|【|（|\(|「)?\s*@([^\s\]】）)」]+)\s*(?:\]{1,2}|】|）|\)|」)?")

_grants_lock = threading.Lock()
_grants: dict[tuple[int, int], dict[str, tuple[int, float]]] = {}


def clear_social_mention_state() -> None:
    with _grants_lock:
        _grants.clear()


def grant_mention(bot_id: int, group_id: int, key: str, qq: int, *, ttl_sec: float = _MENTION_GRANT_TTL_SEC) -> None:
    k = str(key or "").strip()
    if not k:
        return
    with _grants_lock:
        bucket = _grants.setdefault((int(bot_id), int(group_id)), {})
        _prune_expired_locked(bucket, time.time())
        bucket[k] = (int(qq), time.time() + max(1.0, float(ttl_sec)))


def resolve_mention_qq(bot_id: int, group_id: int, key: str) -> int | None:
    k = str(key or "").strip()
    if not k:
        return None
    now = time.time()
    with _grants_lock:
        bucket = _grants.get((int(bot_id), int(group_id)))
        if not bucket:
            return None
        _prune_expired_locked(bucket, now)
        entry = bucket.get(k)
        if entry is None or entry[1] <= now:
            bucket.pop(k, None)
            return None
        return entry[0]


def replace_mention_tokens(text: str, *, bot_id: int, group_id: int) -> str:
    """把已授权的提及占位符替换为 CQ at；带括号的未授权项删除，裸 @ 保留。"""

    def repl(match: re.Match[str]) -> str:
        qq = resolve_mention_qq(bot_id, group_id, match.group(1))
        if qq is not None:
            return f"[CQ:at,qq={qq}]"
        raw = match.group(0)
        return raw if raw.startswith("@") else ""

    return _MENTION_PLACEHOLDER_RE.sub(repl, str(text or ""))


def _prune_expired_locked(bucket: dict[str, tuple[int, float]], now: float) -> None:
    expired = [k for k, (_, expires_at) in bucket.items() if expires_at <= now]
    for k in expired:
        bucket.pop(k, None)


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


async def resolve_master_user_ids(bot_id: int) -> list[int]:
    ids: set[int] = set(parse_superuser_ids())
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
    return str(info.get("card") or info.get("nickname") or "").strip() or None


async def _group_member_rows(bot, group_id: int) -> list[dict[str, Any]]:
    try:
        data = await bot.get_group_member_list(group_id=int(group_id))
    except Exception:
        return []
    return list(data) if isinstance(data, list) else []


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
    bot = await _bot_for(context.bot_id)
    if bot is None:
        return {"ok": False, "error": "bot_unavailable"}
    masters: list[dict[str, Any]] = []
    for index, qq in enumerate(await resolve_master_user_ids(context.bot_id)):
        name = await _member_display_name(bot, context.group_id, qq)
        if name is None:
            continue
        key = f"master_{index}"
        grant_mention(context.bot_id, context.group_id, key, qq)
        grant_mention(context.bot_id, context.group_id, re.sub(r"\s+", "", name), qq)
        masters.append({"key": key, "qq": qq, "name": name})
    if not masters:
        logger.info(
            "social master lookup for bot [{}] in group [{}]: no master present",
            context.bot_id,
            context.group_id,
        )
        return {
            "ok": True,
            "result": {"in_group": False, "masters": []},
            "summary": "主人不在本群，不要透露主人身份或 QQ，如实说主人不在这个群。",
        }
    logger.info(
        "social master lookup for bot [{}] in group [{}]: [{}] master(s) in group [{}]",
        context.bot_id,
        context.group_id,
        len(masters),
        [f"{item['name']}({item['qq']})" for item in masters],
    )
    return {
        "ok": True,
        "result": {
            "in_group": True,
            "masters": masters,
            "hint": "想 @ 主人时在回复中写对应的 [[@key]]（如 [[@master_0]]），不想 @ 就只提名字。",
        },
    }


async def handle_member_find(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    query = str((arguments or {}).get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}
    bot = await _bot_for(context.bot_id)
    if bot is None:
        return {"ok": False, "error": "bot_unavailable"}
    members = await _group_member_rows(bot, context.group_id)
    scored: list[tuple[int, str]] = []
    seen: set[int] = set()
    folded_query = query.casefold()
    for row in members:
        qq = row.get("user_id")
        if qq is None or int(qq) in seen:
            continue
        qq_int = int(qq)
        name = str(row.get("card") or row.get("nickname") or "").strip()
        if not name:
            continue
        folded = name.casefold()
        if folded == folded_query:
            score = 0
        elif folded_query in folded:
            score = 1
        elif folded in folded_query:
            score = 2
        else:
            continue
        seen.add(qq_int)
        scored.append((score, qq_int, name))
    scored.sort(key=lambda item: (item[0], len(item[2])))
    matches: list[dict[str, Any]] = []
    for index, (_score, qq, name) in enumerate(scored[:5]):
        key = f"member_{index}"
        grant_mention(context.bot_id, context.group_id, key, qq)
        grant_mention(context.bot_id, context.group_id, re.sub(r"\s+", "", name), qq)
        matches.append({"key": key, "qq": qq, "name": name})
    if not matches:
        logger.info(
            "social member find query [{}] for bot [{}] in group [{}]: no match",
            query,
            context.bot_id,
            context.group_id,
        )
        return {"ok": True, "result": {"matches": []}, "summary": "没找到匹配的群成员，如实说找不到，不要编造。"}
    logger.info(
        "social member find query [{}] for bot [{}] in group [{}]: [{}] match(es) [{}]",
        query,
        context.bot_id,
        context.group_id,
        len(matches),
        [f"{item['name']}({item['qq']})" for item in matches],
    )
    return {
        "ok": True,
        "result": {
            "matches": matches,
            "hint": "想 @ 某成员时在回复中写对应的 [[@key]]（如 [[@member_0]]），不想 @ 就只提名字。",
        },
    }
