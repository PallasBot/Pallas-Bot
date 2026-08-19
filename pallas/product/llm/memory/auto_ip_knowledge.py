"""自动从群聊提炼可复用的 IP 事实知识（不硬编码 IP 名单，由 LLM 判定）。

与 auto_episode 不同：auto_episode 记「群共同事件」，这里记「跨群通用的 IP 事实」
（如某游戏角色设定、某番剧剧情、某世界观机制），带 (bot, group) 隔离并走记忆向量检索。
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
from pallas.product.llm.memory.rate_limit import DailyBudget, WriteCooldown
from pallas.product.llm.memory.store import is_llm_memory_store_available, save_memory_entry
from pallas.product.llm.provider_client import complete_chat_message
from pallas.product.llm.session_store import list_group_ambient_messages

_last_write_at = WriteCooldown()
_in_flight: set[tuple[int, int]] = set()
_daily_budget = DailyBudget()

_IP_SYSTEM_PROMPT = """你是群聊 IP 知识提炼助手。从群聊摘录中找出「可复用的 IP 事实」。

IP 指任何作品/IP：游戏（如明日方舟、鸣潮）、番剧、电影、音乐、小说、漫画等。
凡是「关于某作品/角色的稳定设定、机制、剧情、人物关系」都属于 IP 事实。

只提炼满足全部条件的：
- 涉及明确 IP（作品/角色/世界观），至少 2 人聊到，不是单人自言自语。
- 是客观、稳定、可复用的事实（设定/机制/关系/剧情），不是个人感受、梗、闲聊、或瞬时事件。
- 群友在讨论并分享信息（哪怕有错，提炼当下讨论中的信息即可）。

每个事实输出一条 JSON，格式：
{"ip": "作品名", "fact": "一句话客观陈述（≤80字）", "keywords": "3-6个检索关键词，逗号分隔"}

没有可提炼的 IP 事实时，只输出空数组 []。不要解释，不要 Markdown，只输出 JSON。"""


def _transcript(turns: list[Any]) -> str:
    user_turns = [turn for turn in turns if str(getattr(turn, "role", "")) == "user"]
    participants = {
        int(getattr(turn, "user_id", 0) or 0) for turn in user_turns if int(getattr(turn, "user_id", 0) or 0)
    }
    if len(user_turns) < 3 or len(participants) < 2:
        return ""
    lines: list[str] = []
    for turn in turns:
        if str(getattr(turn, "role", "")) != "user":
            continue
        text = str(getattr(turn, "content", "") or "").strip()
        if text:
            lines.append(f"群友：{text[:240]}")
    return "\n".join(lines)


def _cooldown_ok(bot_id: int, group_id: int, *, cooldown_sec: int) -> bool:
    return _last_write_at.ok((int(bot_id), int(group_id)), cooldown_sec)


def _mark_written(bot_id: int, group_id: int) -> None:
    _last_write_at.mark((int(bot_id), int(group_id)))


def _daily_budget_ok(*, cfg: LlmConfig) -> bool:
    return _daily_budget.ok(int(cfg.llm_memory_auto_ip_daily_budget))


def _bump_daily_budget(*, cfg: LlmConfig) -> None:
    _daily_budget.bump(int(cfg.llm_memory_auto_ip_daily_budget))


def _parse_facts(raw: str) -> list[dict[str, str]]:
    text = str(raw or "").strip()
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()[:40]
        fact = str(item.get("fact") or "").strip()[:120]
        keywords = str(item.get("keywords") or "").strip()[:200]
        if ip and fact:
            out.append({"ip": ip, "fact": fact, "keywords": keywords})
    return out


def _fact_to_content(item: dict[str, str]) -> str:
    ip = str(item.get("ip") or "").strip()
    fact = str(item.get("fact") or "").strip()
    keywords = str(item.get("keywords") or "").strip()
    if keywords:
        return f"【{ip}】{fact}（关键词：{keywords}）"
    return f"【{ip}】{fact}"


async def maybe_auto_save_ip_knowledge(
    *,
    bot_id: int,
    group_id: int | None,
    cfg: LlmConfig | None = None,
) -> bool:
    """从近期群聊异步提炼 IP 事实写入记忆，失败不影响聊天。"""
    c = cfg or get_llm_config()
    if not c.llm_memory_auto_ip_enabled:
        return False
    if group_id is None or not can_read_persistent_memory(c) or not is_llm_memory_store_available():
        return False
    bid, gid = int(bot_id), int(group_id)
    if not _cooldown_ok(bid, gid, cooldown_sec=c.llm_memory_auto_ip_cooldown_sec):
        return False
    if not _daily_budget_ok(cfg=c):
        return False
    key = (bid, gid)
    if key in _in_flight:
        return False
    _in_flight.add(key)
    try:
        try:
            turns = await list_group_ambient_messages(bid, gid, limit=12, cfg=c)
        except Exception as exc:
            logger.warning("Auto IP knowledge history read failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
            return False
        transcript = _transcript(turns)
        if not transcript:
            return False
        try:
            message = await complete_chat_message(
                [{"role": "system", "content": _IP_SYSTEM_PROMPT}, {"role": "user", "content": transcript}],
                model="",
                options={
                    "temperature": 0,
                    "max_tokens": task_token_budget("memory_extract"),
                },
                task="memory_extract",
                cfg=c,
            )
        except Exception as exc:
            logger.warning("Auto IP knowledge extract failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
            return False
        facts = _parse_facts(str(message.get("content") or "") if isinstance(message, dict) else "")
        if not facts:
            return False
        _bump_daily_budget(cfg=c)
        saved = 0
        for item in facts:
            ok = await save_memory_entry(
                bid,
                gid,
                _fact_to_content(item),
                source="auto_ip_knowledge",
                cfg=c,
            )
            if ok:
                saved += 1
        if saved:
            _mark_written(bid, gid)
            logger.info(
                "Auto IP knowledge saved {} fact(s) for bot [{}] in group [{}]",
                saved,
                bid,
                gid,
            )
            return True
        return False
    finally:
        _in_flight.discard(key)


def schedule_auto_save_ip_knowledge(*, bot_id: int, group_id: int | None, cfg: LlmConfig | None = None) -> None:
    c = cfg or get_llm_config()
    if group_id is None or not c.llm_memory_auto_ip_enabled:
        return
    try:
        asyncio.get_running_loop().create_task(
            maybe_auto_save_ip_knowledge(bot_id=bot_id, group_id=group_id, cfg=c),
            name=f"auto_ip_knowledge:{bot_id}:{group_id}",
        )
    except RuntimeError:
        return


def clear_auto_ip_cooldown_for_tests() -> None:
    _last_write_at.clear()
    _in_flight.clear()
    _daily_budget.reset()


def auto_ip_status_snapshot() -> dict[str, Any]:
    return {
        "tracked_groups": _last_write_at.tracked(),
        "in_flight": len(_in_flight),
        "daily_budget_used": _daily_budget.used(),
    }
