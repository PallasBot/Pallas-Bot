"""入站别名路由：正文点名某只牛时，其他牛让出 claim。"""

from __future__ import annotations

from threading import Lock

_learned_lock = Lock()
_learned_self_aliases: dict[int, tuple[str, ...]] = {}


def clear_alias_route_state() -> None:
    with _learned_lock:
        _learned_self_aliases.clear()


def remember_learned_self_aliases(bot_id: int, aliases: list[str]) -> None:
    cleaned = tuple(str(item or "").strip() for item in aliases if str(item or "").strip())
    with _learned_lock:
        if cleaned:
            _learned_self_aliases[int(bot_id)] = cleaned
        else:
            _learned_self_aliases.pop(int(bot_id), None)


def cached_learned_self_aliases(bot_id: int) -> list[str]:
    with _learned_lock:
        return list(_learned_self_aliases.get(int(bot_id), ()))


def speak_aliases_for_bot_sync(bot_id: int) -> list[str]:
    from pallas.product.persona.self_identity import (
        extract_self_aliases,
        resolve_cached_login_nickname,
    )

    nick = resolve_cached_login_nickname(int(bot_id))
    learned = cached_learned_self_aliases(int(bot_id))
    persona = {"self_aliases": learned} if learned else None
    return extract_self_aliases(persona, login_nickname=nick or None)


def speak_exclusive_aliases_for_bot_sync(bot_id: int) -> list[str]:
    from pallas.product.persona.self_identity import (
        extract_exclusive_self_aliases,
        resolve_cached_login_nickname,
    )

    nick = resolve_cached_login_nickname(int(bot_id))
    learned = cached_learned_self_aliases(int(bot_id))
    persona = {"self_aliases": learned} if learned else None
    return extract_exclusive_self_aliases(persona, login_nickname=nick or None)


def fleet_bots_matching_plain(plain_text: str, *, min_alias_len: int = 2) -> frozenset[int]:
    from pallas.core.platform.multi_bot.fleet import get_fleet_bot_ids
    from pallas.product.llm.speak_perception import text_mentions_aliases

    plain = str(plain_text or "").strip()
    if not plain:
        return frozenset()
    hits: set[int] = set()
    for raw_id in get_fleet_bot_ids():
        bot_id = int(raw_id)
        aliases = speak_exclusive_aliases_for_bot_sync(bot_id)
        if text_mentions_aliases(plain, aliases, min_alias_len=min_alias_len):
            hits.add(bot_id)
    return frozenset(hits)


def should_yield_ingress_for_peer_alias(
    *,
    self_id: int,
    plain_text: str,
    min_alias_len: int = 2,
) -> bool:
    """正文命中同伴别名且未命中自己时，让出抢占。"""
    matched = fleet_bots_matching_plain(plain_text, min_alias_len=min_alias_len)
    if not matched:
        return False
    return int(self_id) not in matched
