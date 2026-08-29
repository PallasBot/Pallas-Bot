"""自动从单用户近期消息提炼稳定的个人偏好，写入 person_facts。

与 auto_ip_knowledge 不同：这里按 (user, group) 归纳「个人稳定特点」
（如爱发表情包、喜欢某话题、偏好寒暄方式），观察侧重宽容，只记录
「明显、稳定、可复用」的偏好，避免把一时闲聊当特点。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.kernel.memory_governance import can_read_persistent_memory
from pallas.product.llm.memory.person_facts import list_person_facts, save_person_fact
from pallas.product.llm.memory.rate_limit import DailyBudget, WriteCooldown
from pallas.product.llm.provider_client import complete_chat_message
from pallas.product.llm.session_store import list_user_llm_messages

_last_write_at = WriteCooldown()
_in_flight: set[tuple[int, int, int]] = set()
_daily_budget = DailyBudget()

_USER_TURNS_LIMIT = 8
_MAX_FACT_LEN = 64

_SYSTEM_PROMPT = """你是群聊人格观察助手。根据「某个群友」最近的发言，归纳 ta 明显、稳定、可复用的个人特点或偏好。

只记录满足全部条件的：
- 明显且多次体现的习惯/兴趣/偏好（如「爱发表情包」「喜欢某游戏」「称某群友为老哥」「讨厌剧透」）。
- 是稳定的个人特点，不是一次性事件、临时情绪或某句玩笑。
- 观察要宽容：不确定的、推测的不要记，宁缺毋滥。

每条输出一句流畅的中文陈述（≤50字），不用敬称，不要出现「tag/标签」等字样。格式：
{"facts": ["…", "…"]}

没有任何值得记的个人特点时，只输出空数组 {"facts": []}。不要解释，不要 Markdown，只输出 JSON。"""


def _user_turns(turns: list[Any]) -> str:
    lines: list[str] = []
    seen: set[int] = set()
    for turn in turns:
        if str(getattr(turn, "role", "")) != "user":
            continue
        user_id = int(getattr(turn, "user_id", 0) or 0)
        text = str(getattr(turn, "content", "") or "").strip()
        if not text or not user_id:
            continue
        if len(lines) >= _USER_TURNS_LIMIT:
            break
        seen.add(user_id)
        lines.append(text[:240])
    if not lines or len(seen) < 1:
        return ""
    return "\n".join(lines)


def _cooldown_ok(bot_id: int, group_id: int, user_id: int, *, cooldown_sec: int) -> bool:
    return _last_write_at.ok((int(bot_id), int(group_id), int(user_id)), cooldown_sec)


def _mark_written(bot_id: int, group_id: int, user_id: int) -> None:
    _last_write_at.mark((int(bot_id), int(group_id), int(user_id)))


def _daily_budget_ok(*, cfg: LlmConfig) -> bool:
    return _daily_budget.ok(int(cfg.llm_memory_auto_person_facts_daily_budget))


def _bump_daily_budget(*, cfg: LlmConfig) -> None:
    _daily_budget.bump(int(cfg.llm_memory_auto_person_facts_daily_budget))


def _parse_facts(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = item.get("facts") if isinstance(item.get("facts"), list) else []
        for fact in candidates:
            content = str(fact or "").strip().rstrip("。").strip()
            if content:
                out.append(content[:_MAX_FACT_LEN])
    return out


def _existing_contents(*, bot_id: int, group_id: int, user_id: int) -> set[str]:
    return {
        fact.content.casefold()
        for fact in list_person_facts(bot_id=bot_id, group_id=group_id, user_id=user_id, limit=200)
        if fact.status == "active"
    }


async def maybe_auto_save_person_facts(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int | None,
    cfg: LlmConfig | None = None,
) -> int:
    """从用户近期消息异步提炼稳定偏好写入 person_facts，失败不影响聊天。"""
    c = cfg or get_llm_config()
    if not c.llm_memory_auto_person_facts_enabled:
        return 0
    if group_id is None or not user_id or not can_read_persistent_memory(c):
        return 0
    bid, gid, uid = int(bot_id), int(group_id), int(user_id)
    if not _cooldown_ok(bid, gid, uid, cooldown_sec=c.llm_memory_auto_person_facts_cooldown_sec):
        return 0
    if not _daily_budget_ok(cfg=c):
        return 0
    key = (bid, gid, uid)
    if key in _in_flight:
        return 0
    _in_flight.add(key)
    try:
        try:
            turns = await list_user_llm_messages(bid, gid, uid, limit=_USER_TURNS_LIMIT, cfg=c)
        except Exception as exc:
            logger.warning("Auto person facts history read failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
            return 0
        transcript = _user_turns(turns)
        if not transcript:
            return 0
        try:
            message = await complete_chat_message(
                [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": transcript}],
                model="",
                options={
                    "temperature": 0.3,
                    "max_tokens": task_token_budget("memory_extract"),
                },
                task="memory_extract",
                cfg=c,
            )
        except Exception as exc:
            logger.warning("Auto person facts extract failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
            return 0
        facts = _parse_facts(str(message.get("content") or "") if isinstance(message, dict) else "")
        if not facts:
            return 0
        existing = _existing_contents(bot_id=bid, group_id=gid, user_id=uid)
        saved = 0
        for content in facts:
            if content.casefold() in existing:
                continue
            try:
                save_person_fact(
                    bot_id=bid,
                    group_id=gid,
                    user_id=uid,
                    content=content,
                    source="conversation",
                    confidence=0.7,
                    scope="group",
                )
                saved += 1
                existing.add(content.casefold())
            except Exception as exc:
                logger.warning("Auto person fact save failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
        if saved:
            _bump_daily_budget(cfg=c)
            _mark_written(bid, gid, uid)
            logger.info("Auto person facts saved {} fact(s) for user [{}] in group [{}]", saved, uid, gid)
        return saved
    finally:
        _in_flight.discard(key)


def schedule_auto_save_person_facts(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int | None,
    cfg: LlmConfig | None = None,
) -> None:
    c = cfg or get_llm_config()
    if group_id is None or not user_id or not c.llm_memory_auto_person_facts_enabled:
        return
    if not _cooldown_ok(
        int(bot_id),
        int(group_id),
        int(user_id),
        cooldown_sec=c.llm_memory_auto_person_facts_cooldown_sec,
    ) or not _daily_budget_ok(cfg=c):
        return
    try:
        asyncio.get_running_loop().create_task(
            maybe_auto_save_person_facts(bot_id=bot_id, group_id=group_id, user_id=user_id, cfg=c),
            name=f"auto_person_facts:{bot_id}:{group_id}:{user_id}",
        )
    except RuntimeError:
        return


def clear_auto_person_facts_cooldown_for_tests() -> None:
    _last_write_at.clear()
    _in_flight.clear()
    _daily_budget.reset()


def auto_person_facts_status_snapshot() -> dict[str, Any]:
    return {
        "tracked_users": _last_write_at.tracked(),
        "in_flight": len(_in_flight),
        "daily_budget_used": _daily_budget.used(),
    }
