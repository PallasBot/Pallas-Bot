"""同伴牛牛：persona 注入、教导句式、表达库拒收。"""

from __future__ import annotations

import re
from typing import Any

from pallas.product.persona.prompt_guard import sanitize_prompt_literal, wrap_stats_block
from pallas.product.persona.self_identity import resolve_cached_login_nickname

_PEER_TEACH_RE = re.compile(
    r"^(?:记住[：:\s]*)?"
    r"(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12}?)"
    r"(?:也是|是)"
    r"(?:同伴(?:牛牛)?|牛牛同伴|另一只牛牛|其他牛牛|同伴|牛牛)$"
)

_PEER_HARM_RE = re.compile(r"(?:其他牛牛|别的牛牛|打死.{0,8}牛|打了其他|哪只都不舍得打死|没留活口|打成牛肉丸)")
_PEER_REFERENCE_RE = re.compile(r"(?:其他|别的|另一只|同伴)(?:的)?牛+(?:们)?|哪只牛+")

_PEER_ALIAS_BLOCKLIST = frozenset({
    "我",
    "你",
    "牛牛",
    "帕拉斯",
    "pallas",
    "bot",
    "谁",
    "什么",
    "啥",
    "哪位",
    "哪个",
    "机器人",
    "同伴",
})


def is_peer_harm_expression(text: str) -> bool:
    """不宜写入表达库 / 好样本 few-shot 的同伴误伤玩梗。"""
    plain = str(text or "").strip()
    if not plain:
        return False
    return bool(_PEER_HARM_RE.search(plain))


def _safe_peer_alias(raw: str) -> str | None:
    text = sanitize_prompt_literal(str(raw or "").strip(), max_len=16)
    if not text:
        return None
    if text.casefold() in {item.casefold() for item in _PEER_ALIAS_BLOCKLIST}:
        return None
    if len(text) < 2:
        return None
    return text


def parse_peer_alias_teach(plain_text: str) -> list[str]:
    body = str(plain_text or "").strip()
    if not body or len(body) > 48:
        return []
    # 避免与自称教导冲突（「牛牛就是我」等）
    if re.search(r"(?:就是我|是我|就是你|是你|指的是你)$", body):
        return []
    matched = _PEER_TEACH_RE.match(body)
    if not matched:
        return []
    safe = _safe_peer_alias(str(matched.group("alias") or ""))
    return [safe] if safe else []


def extract_taught_peer_aliases(bot_persona: dict[str, Any] | None) -> list[str]:
    if not isinstance(bot_persona, dict):
        return []
    raw = bot_persona.get("peer_aliases")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        safe = _safe_peer_alias(str(item or ""))
        if not safe or safe.casefold() in seen:
            continue
        seen.add(safe.casefold())
        out.append(safe)
    return out[:8]


def resolve_peer_bot_labels(self_bot_id: int, *, limit: int = 8) -> list[str]:
    """本部署其他牛牛展示名（昵称优先）。"""
    try:
        from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids

        peers = sorted(int(qq) for qq in get_catalog_bot_ids() if int(qq) != int(self_bot_id))
    except Exception:
        peers = []
    labels: list[str] = []
    seen: set[str] = set()
    for qq in peers:
        if len(labels) >= limit:
            break
        nick = resolve_cached_login_nickname(int(qq)).strip()
        label = sanitize_prompt_literal(nick, max_len=16) if nick else ""
        if not label:
            # 无昵称时用短尾巴，避免整段 QQ
            label = f"牛牛{str(int(qq))[-4:]}"
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


def compile_peer_bots_prompt(
    *,
    self_bot_id: int,
    peer_labels: list[str] | None = None,
    taught_aliases: list[str] | None = None,
    bot_persona: dict[str, Any] | None = None,
) -> str:
    labels = list(peer_labels) if peer_labels is not None else resolve_peer_bot_labels(int(self_bot_id))
    taught = list(taught_aliases) if taught_aliases is not None else extract_taught_peer_aliases(bot_persona)
    names: list[str] = []
    seen: set[str] = set()
    for item in [*labels, *taught]:
        safe = sanitize_prompt_literal(str(item or "").strip(), max_len=16)
        if not safe or safe.casefold() in seen:
            continue
        seen.add(safe.casefold())
        names.append(safe)
    if not names:
        return ""
    name_text = "、".join(names[:8])
    body = "\n".join([
        "【同伴牛牛】",
        f"- 同部署还有其他帕拉斯账号：{name_text}。他们和你一样是牛牛同伴。",
        "- 有人提「其他牛牛 / 哪只牛牛 / 某某牛」时，优先理解为同伴账号，不是外人，更不是要打的对象。",
        "- 不要宣称「我打死了其他牛牛」或替同伴受过；可以说「那是另一只牛牛在说话」。",
    ])
    return wrap_stats_block("peer_bots", body)


def compile_peer_bots_prompt_for_message(
    *,
    self_bot_id: int,
    plain_text: str,
    peer_labels: list[str] | None = None,
    taught_aliases: list[str] | None = None,
    bot_persona: dict[str, Any] | None = None,
) -> str:
    labels = list(peer_labels) if peer_labels is not None else resolve_peer_bot_labels(int(self_bot_id))
    taught = list(taught_aliases) if taught_aliases is not None else extract_taught_peer_aliases(bot_persona)
    plain = str(plain_text or "").strip().casefold()
    names: list[str] = []
    for item in [*labels, *taught]:
        safe = _safe_peer_alias(str(item or ""))
        if safe:
            names.append(safe.casefold())
    if not plain or (not _PEER_REFERENCE_RE.search(plain) and not any(name in plain for name in names)):
        return ""
    return compile_peer_bots_prompt(
        self_bot_id=self_bot_id,
        peer_labels=labels,
        taught_aliases=taught,
        bot_persona=bot_persona,
    )


def compile_repeater_peer_bots_prompt(
    *,
    self_bot_id: int,
    bot_persona: dict[str, Any] | None = None,
) -> str:
    labels = resolve_peer_bot_labels(int(self_bot_id), limit=4)
    taught = extract_taught_peer_aliases(bot_persona)
    names = []
    seen: set[str] = set()
    for item in [*labels, *taught]:
        safe = sanitize_prompt_literal(str(item or "").strip(), max_len=16)
        if not safe or safe.casefold() in seen:
            continue
        seen.add(safe.casefold())
        names.append(safe)
    if not names:
        return ""
    name_text = "、".join(names[:4])
    body = "\n".join([
        "【同伴】",
        f"- 群里/同部署还有其他牛牛（如 {name_text}），提及时当同伴账号，别当成外人玩梗对象。",
    ])
    return wrap_stats_block("peer_bots", body)


async def merge_peer_aliases(bot_id: int, aliases: list[str]) -> bool:
    from pallas.core.foundation.db import make_bot_config_repository

    cleaned = [item for item in (_safe_peer_alias(alias) for alias in aliases) if item]
    if not cleaned:
        return False
    repo = make_bot_config_repository()
    doc = await repo.get(int(bot_id))
    persona: dict[str, Any] = {}
    if doc is not None and isinstance(getattr(doc, "persona", None), dict):
        persona = dict(doc.persona)
    merged = extract_taught_peer_aliases(persona)
    seen = {item.casefold() for item in merged}
    changed = False
    for alias in cleaned:
        if alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        merged.append(alias)
        changed = True
    if not changed:
        return True
    persona["peer_aliases"] = merged[:8]
    await repo.upsert_field(int(bot_id), "persona", persona)
    return True


async def save_peer_alias_from_teach(bot_id: int, plain_text: str) -> bool:
    aliases = parse_peer_alias_teach(plain_text)
    if not aliases:
        return False
    return await merge_peer_aliases(bot_id, aliases)
