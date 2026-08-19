"""消息发送者身份：区分本 bot / 同部署及协作 bot / 真人，避免 bot 发言被当群友。"""

from __future__ import annotations

from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_peer_bot_cache: frozenset[int] | None = None


def clear_sender_identity_cache() -> None:
    global _peer_bot_cache
    _peer_bot_cache = None


def peer_bot_ids() -> frozenset[int]:
    """同部署 + 联邦协作 bot 的 QQ 集合；运行时装缓存，避免频繁读 Redis。"""
    global _peer_bot_cache
    if _peer_bot_cache is not None:
        return _peer_bot_cache
    ids: set[int] = set()
    try:
        from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids

        ids.update(int(qq) for qq in get_catalog_bot_ids())
    except Exception:
        pass
    try:
        from pallas.core.platform.federate.peer_bots import get_federate_peer_bot_ids

        ids.update(int(qq) for qq in get_federate_peer_bot_ids())
    except Exception:
        pass
    _peer_bot_cache = frozenset(ids)
    return _peer_bot_cache


def is_peer_bot(user_id: object) -> bool:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    return uid in peer_bot_ids()


def sender_kind(user_id: object, *, self_bot_id: object) -> str:
    """返回 self / peer_bot / human 之一。"""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return "human"
    try:
        self_id = int(self_bot_id)
    except (TypeError, ValueError):
        self_id = 0
    if uid > 0 and uid == self_id:
        return "self"
    return "peer_bot" if is_peer_bot(uid) else "human"


def speaker_label(
    user_id: object,
    sender_name: object,
    *,
    self_bot_id: object,
    self_label: str = "牛牛",
    peer_label: str = "别的牛",
) -> str:
    """给消息发送者一个面向模型的称呼：本 bot / 其他 bot / 真人昵称。"""
    kind = sender_kind(user_id, self_bot_id=self_bot_id)
    if kind == "self":
        return self_label
    if kind == "peer_bot":
        return peer_label
    name = sanitize_prompt_literal(str(sender_name or ""), max_len=40)
    if name:
        return name
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        uid = 0
    return f"群友#{uid % 10000:04d}"
