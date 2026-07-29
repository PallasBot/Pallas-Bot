"""Bot 自称与群昵称（如「牛牛」）注入 persona prompt。"""

from __future__ import annotations

import re
from typing import Any

from pallas.core.foundation.db import make_bot_config_repository
from pallas.product.persona.prompt_guard import sanitize_prompt_literal, wrap_stats_block

DEFAULT_GENERIC_ALIASES: tuple[str, ...] = ("牛牛",)
# 兼容旧引用；默认全员通称不再广播「帕拉斯」「Pallas」。
DEFAULT_SELF_ALIASES: tuple[str, ...] = DEFAULT_GENERIC_ALIASES

_SELF_ALIAS_TEACH_RE = re.compile(
    r"^(?:记住[：:]?\s*)?"
    r"(?P<alias>.+?)"
    r"(?:就是我|是我)$"
)
_SELF_ALIAS_IS_YOU_RE = re.compile(
    r"^(?:记住[：:]?\s*)?"
    r"(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})"
    r"(?:就是你|是你)$"
)
_SELF_ALIAS_POINTS_YOU_RE = re.compile(
    r"^(?:记住[：:]?\s*)?"
    r"(?P<alias>.+?)"
    r"(?:指的是你|就是指你|指的是bot|指的是机器人)$",
    re.IGNORECASE,
)
_SELF_ALIAS_EQUALS_RE = re.compile(r"^(?P<left>[\u4e00-\u9fffA-Za-z·]{1,12})\s*[=＝]\s*(?:我|你|bot|Bot|机器人)$")
_SELF_ALIAS_MEANS_RE = re.compile(
    r"^(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})\s*(?:指的是|就是指|就是)\s*(?:你|我|bot|Bot|机器人)$"
)
# 观察型称呼：不打断对话，静默写入 self_aliases
_SELF_ALIAS_OBSERVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^大家(?:都)?叫你(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})$"),
    re.compile(r"^群友(?:都)?叫你(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})$"),
    re.compile(r"^你的(?:外号|昵称|群名片)(?:是|叫)(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})$"),
    re.compile(r"^(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})是你的(?:外号|昵称|群名片)$"),
    re.compile(r"^你(?:就)?是(?P<alias>[\u4e00-\u9fffA-Za-z·]{2,12})$"),
)
_ALIAS_BLOCKLIST = frozenset({
    "我",
    "你",
    "bot",
    "谁",
    "什么",
    "啥",
    "哪位",
    "哪个",
    "机器人",
    # 观察/问句碎片误沉淀
    "说的",
    "这",
    "那",
    "哪只",
    "哪只牛",
    "哪只牛牛",
    "什么牛",
    "傻逼吗",
    "什么吗",
    "谁啊",
    "干嘛",
    "咋了",
    "在吗",
})

# 别名若命中这些子串，视为问句/脏话碎片
_ALIAS_BAD_SUBSTR = ("哪只", "什么牛", "傻逼", "吗", "谁啊", "咋了", "干嘛")
_ALIAS_BLOCKLIST_CASEFOLDS = frozenset(item.casefold() for item in _ALIAS_BLOCKLIST)
_DEFAULT_GENERIC_ALIAS_CASEFOLDS = frozenset(item.casefold() for item in DEFAULT_GENERIC_ALIASES)


def _safe_alias(raw: str) -> str | None:
    safe = sanitize_prompt_literal(str(raw or "").strip(), max_len=16)
    if not safe or safe.casefold() in _ALIAS_BLOCKLIST_CASEFOLDS:
        return None
    if len(safe) < 2:
        return None
    if any(token in safe for token in ("哪只", "什么牛", "傻逼")):
        return None
    if safe.endswith(("吗", "？", "?")):
        return None
    return safe


def shorten_niu_niu_compound_alias(raw: str) -> str | None:
    text = _safe_alias(raw) or ""
    if not text or text == "牛牛":
        return None
    if text.startswith("牛牛") and len(text) > 2:
        return _safe_alias(text[2:])
    if text.endswith("牛牛") and len(text) > 2:
        return _safe_alias(text[:-2])
    return None


def _append_alias(aliases: list[str], seen: set[str], raw: str) -> None:
    text = _safe_alias(raw)
    if not text or text.casefold() in seen:
        return
    seen.add(text.casefold())
    aliases.append(text)


def _append_exclusive_alias(aliases: list[str], seen: set[str], raw: str) -> None:
    text = _safe_alias(raw)
    if not text or text.casefold() in _DEFAULT_GENERIC_ALIAS_CASEFOLDS:
        return
    _append_alias(aliases, seen, text)
    shortened = shorten_niu_niu_compound_alias(text)
    if shortened and shortened.casefold() not in _DEFAULT_GENERIC_ALIAS_CASEFOLDS:
        _append_alias(aliases, seen, shortened)


def extract_generic_self_aliases() -> list[str]:
    return list(DEFAULT_GENERIC_ALIASES)


def extract_exclusive_self_aliases(
    bot_persona: dict[str, Any] | None,
    *,
    login_nickname: str | None = None,
) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    _append_exclusive_alias(aliases, seen, str(login_nickname or ""))
    if not isinstance(bot_persona, dict):
        return aliases
    raw = bot_persona.get("self_aliases")
    if raw is None:
        raw = bot_persona.get("alias_names")
    if not isinstance(raw, list):
        return aliases
    for item in raw:
        _append_exclusive_alias(aliases, seen, str(item or ""))
    return aliases


def extract_raw_learned_self_aliases(bot_persona: dict[str, Any] | None) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    if not isinstance(bot_persona, dict):
        return aliases
    raw = bot_persona.get("self_aliases")
    if raw is None:
        raw = bot_persona.get("alias_names")
    if not isinstance(raw, list):
        return aliases
    for item in raw:
        _append_alias(aliases, seen, str(item or ""))
    return aliases


def extract_self_aliases(
    bot_persona: dict[str, Any] | None,
    *,
    login_nickname: str | None = None,
) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for item in extract_exclusive_self_aliases(bot_persona, login_nickname=login_nickname):
        _append_alias(aliases, seen, item)
    for item in extract_generic_self_aliases():
        _append_alias(aliases, seen, item)
    return aliases


def compile_self_identity_prompt(
    bot_persona: dict[str, Any] | None = None,
    *,
    login_nickname: str | None = None,
) -> str:
    generic_aliases = extract_generic_self_aliases()
    exclusive_aliases = extract_exclusive_self_aliases(bot_persona, login_nickname=login_nickname)
    generic_text = "、".join(generic_aliases[:4]) or "牛牛"
    exclusive_text = "、".join(exclusive_aliases[:6])
    primary_alias = exclusive_aliases[0] if exclusive_aliases else (generic_aliases[0] if generic_aliases else "牛牛")
    if exclusive_aliases:
        call_line = f"- 群友会用通称「{generic_text}」叫你；若喊专属称呼如「{primary_alias}」等，也是在叫你本人。"
    else:
        call_line = f"- 群友常用通称「{generic_text}」叫你——这些称呼默认都在跟你说话。"
    body = "\n".join([
        "【自称与群称呼】",
        call_line,
        f"- 通称：{generic_text}。",
        f"- 专属称呼：{exclusive_text}。" if exclusive_text else "- 当前没有额外专属称呼；学到后也应视为在喊你。",
        "- 有人 @ 你或在句中喊上述名字时，默认是在跟你说话；用第一人称接话，不要当成第三者在聊。",
        "- 禁止把「牛牛」当外人夸奖（错误：「牛牛真棒」）；应理解成在说你，"
        "用「谢谢」「收到」等第一人称回应，勿用「还行吧」「行行行」起手。",
        "- 自称优先用「我」；必要时可用群昵称指代自己，但不要每句都加动物口癖或句尾 ASCII 颜文字。",
    ])
    return wrap_stats_block("self_identity", body)


def compile_repeater_self_identity_prompt(
    bot_persona: dict[str, Any] | None = None,
    *,
    login_nickname: str | None = None,
) -> str:
    generic_aliases = extract_generic_self_aliases()
    exclusive_aliases = extract_exclusive_self_aliases(bot_persona, login_nickname=login_nickname)
    generic_text = "、".join(generic_aliases[:4]) or "牛牛"
    primary_alias = exclusive_aliases[0] if exclusive_aliases else (generic_aliases[0] if generic_aliases else "牛牛")
    if not exclusive_aliases:
        call_line = f"- 群友喊「{generic_text}」等时是在跟你说话；用第一人称接，别把称呼当第三者在聊。"
    else:
        call_line = (
            f"- 群友喊通称「{generic_text}」或专属称呼「{primary_alias}」等时，"
            "都可能是在跟你说话；用第一人称接，别把称呼当第三者在聊。"
        )
    body = "\n".join([
        "【群称呼】",
        call_line,
        (
            f"- 你的专属称呼：{'、'.join(exclusive_aliases[:6])}。"
            if exclusive_aliases
            else f"- 当前只使用通称「{generic_text}」。"
        ),
        "- 日常接话不必自我介绍帕拉斯或罗德岛，像群友顺口回一句即可。",
    ])
    return wrap_stats_block("self_identity", body)


def resolve_cached_login_nickname(bot_id: int) -> str:
    """同步尽力取昵称：presence → 协议 accounts display_name。"""
    sid = str(int(bot_id))
    try:
        from pallas.core.platform.shard.presence import read_presence_bots

        rec = read_presence_bots().get(sid)
        if isinstance(rec, dict):
            nick = str(rec.get("nickname") or "").strip()
            if nick:
                return nick
    except Exception:
        pass
    try:
        from pallas.console.webui.protocol_accounts import protocol_account_display_names

        return str(protocol_account_display_names().get(sid) or "").strip()
    except Exception:
        return ""


async def resolve_login_nickname(bot_id: int) -> str:
    """优先 OneBot get_login_info，失败则回退缓存。"""
    sid = str(int(bot_id))
    try:
        from nonebot import get_bots

        bot = get_bots().get(sid)
        if bot is not None:
            raw = await bot.call_api("get_login_info")  # type: ignore[union-attr]
            if isinstance(raw, dict):
                nick = str(raw.get("nickname") or "").strip()
                if nick:
                    return nick
    except Exception:
        pass
    return resolve_cached_login_nickname(bot_id)


def parse_self_alias_teach(plain_text: str) -> list[str]:
    body = str(plain_text or "").strip()
    if not body or len(body) > 48:
        return []
    for pattern in (
        _SELF_ALIAS_POINTS_YOU_RE,
        _SELF_ALIAS_MEANS_RE,
        _SELF_ALIAS_EQUALS_RE,
        _SELF_ALIAS_IS_YOU_RE,
        _SELF_ALIAS_TEACH_RE,
    ):
        matched = pattern.match(body)
        if not matched:
            continue
        alias = str(matched.groupdict().get("alias") or matched.groupdict().get("left") or "").strip()
        safe = _safe_alias(alias)
        if safe:
            return [safe]
    return []


def parse_self_alias_observe(plain_text: str) -> list[str]:
    """弱模式：从闲聊句沉淀称呼，不打断主对话。"""
    body = str(plain_text or "").strip()
    if not body or len(body) > 32:
        return []
    if parse_self_alias_teach(body):
        return []
    for pattern in _SELF_ALIAS_OBSERVE_PATTERNS:
        matched = pattern.match(body)
        if not matched:
            continue
        safe = _safe_alias(str(matched.group("alias") or ""))
        if safe:
            return [safe]
    return []


async def merge_self_aliases(bot_id: int, aliases: list[str]) -> bool:
    cleaned = [item for item in (_safe_alias(alias) for alias in aliases) if item]
    if not cleaned:
        return False
    repo = make_bot_config_repository()
    doc = await repo.get(int(bot_id))
    persona: dict[str, Any] = {}
    if doc is not None and isinstance(getattr(doc, "persona", None), dict):
        persona = dict(doc.persona)
    merged = extract_raw_learned_self_aliases(persona)
    seen = {item.casefold() for item in merged}
    changed = False
    for alias in cleaned:
        if alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        merged.append(alias)
        changed = True
    stored = [item for item in merged if item.casefold() not in _DEFAULT_GENERIC_ALIAS_CASEFOLDS][:8]
    try:
        from pallas.core.platform.ingress.alias_route import remember_learned_self_aliases

        remember_learned_self_aliases(int(bot_id), stored)
    except Exception:
        pass
    if not changed:
        return True
    persona["self_aliases"] = stored
    await repo.upsert_field(int(bot_id), "persona", persona)
    return True


async def save_self_alias_from_teach(bot_id: int, plain_text: str) -> bool:
    aliases = parse_self_alias_teach(plain_text)
    if not aliases:
        return False
    return await merge_self_aliases(bot_id, aliases)


async def maybe_persist_self_alias_from_utterance(bot_id: int, plain_text: str) -> bool:
    aliases = parse_self_alias_observe(plain_text)
    if not aliases:
        return False
    return await merge_self_aliases(bot_id, aliases)
