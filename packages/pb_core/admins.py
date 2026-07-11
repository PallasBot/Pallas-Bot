"""号主入库：解析参数并写入 bot_config.admins。"""

from __future__ import annotations

import re

from pallas.core.foundation.command_prefix import extract_command_tail
from pallas.core.foundation.db import make_bot_config_repository

ADD_BOT_ADMIN_COMMAND = "牛牛添加号主"

_QQ_RE = re.compile(r"(?<![0-9])([1-9][0-9]{4,14})(?![0-9])")
# 显式指定目标牛：关键字 + 空格 + QQ，如「牛 3888888888」「牛牛 3888888888」（bot/account 同理，大小写不敏感）
_TARGET_RE = re.compile(r"(?:牛牛|牛|bot|account)\s+([1-9][0-9]{4,14})", re.IGNORECASE)


def collect_qq_ids_from_plain_and_message(plain_text: str, message) -> list[int]:
    ids: list[int] = []
    for seg in message:
        if seg.type != "at":
            continue
        qq = seg.data.get("qq")
        if qq in (None, "all", "0"):
            continue
        try:
            ids.append(int(qq))
        except (TypeError, ValueError):
            continue
    ids.extend(int(m.group(1)) for m in _QQ_RE.finditer(plain_text or ""))
    out: list[int] = []
    seen: set[int] = set()
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    return out


def parse_add_bot_admin_targets(plain_text: str, message, *, self_id: int) -> tuple[int, list[int]] | None:
    """
    解析「牛牛添加号主」目标。

    - 默认所有 QQ（文本或 @）都作为「当前对话牛」的号主。
    - 仅当显式带目标牛关键字（``牛 QQ`` / ``牛牛 QQ`` / ``bot QQ`` / ``account QQ``，关键字后空格接 QQ）时，
      才把该 QQ 作为目标牛，其余 QQ 作为该目标牛的号主。
    """
    tail = extract_command_tail(plain_text, ADD_BOT_ADMIN_COMMAND)
    source = tail or (plain_text or "")
    bot_id = int(self_id)
    match = _TARGET_RE.search(source)
    if match:
        bot_id = int(match.group(1))
        source = source[: match.start()] + source[match.end() :]
    admin_ids = collect_qq_ids_from_plain_and_message(source, message)
    admins = [uid for uid in admin_ids if uid != bot_id]
    if not admins:
        return None
    return bot_id, admins


async def add_bot_admins(bot_id: int, admin_ids: list[int]) -> tuple[bool, list[int], list[int]]:
    """
    确保 bot_config 行存在，并合并号主 QQ。

    数据真相：写入 admin_members（scope="bot"）；同时镜像到 BotConfig.admins 以便
    未完成迁移时回退。

    返回 (是否新建行, 合并后的 admins, 本次新增 QQ)。
    """
    from pallas.core.foundation.config.bot_admins_cache import invalidate_bot_admins_cache
    from pallas.core.foundation.db import make_admin_repository

    admin_repo = make_admin_repository()
    repo = make_bot_config_repository()
    _, created = await repo.get_or_create(bot_id, disabled_plugins=[])
    doc = await repo.get(bot_id, ignore_cache=True)
    current = list(doc.admins or []) if doc else []
    merged = list(current)
    added: list[int] = []
    for admin_id in admin_ids:
        if admin_id == bot_id or admin_id in merged:
            continue
        merged.append(admin_id)
        added.append(admin_id)
    if added or created:
        await repo.upsert_field(bot_id, "admins", merged)
        await repo.invalidate_cache()
        await invalidate_bot_admins_cache(bot_id)
        for admin_id in added:
            try:
                await admin_repo.upsert_member(
                    user_id=int(admin_id),
                    scope="bot",
                    bot_id=int(bot_id),
                )
            except Exception:
                # admin_members 写入失败不阻塞号主命令
                pass
        # ACL 引擎 cache 依赖 admin_members 变更需失效
        try:
            from pallas.core.perm.acl import clear_acl_cache

            clear_acl_cache()
        except Exception:
            pass
    return created, merged, added


def format_add_bot_admin_result(
    *,
    bot_id: int,
    created: bool,
    merged: list[int],
    added: list[int],
) -> str:
    if created and added:
        return (
            f"已为牛牛 {bot_id} 初始化库配置，并添加号主：{', '.join(map(str, added))}。"
            f"当前号主：{', '.join(map(str, merged)) or '（无）'}"
        )
    if created and not added:
        return f"已为牛牛 {bot_id} 初始化库配置；未指定新的号主 QQ。"
    if added:
        return (
            f"已为牛牛 {bot_id} 添加号主：{', '.join(map(str, added))}。"
            f"当前号主：{', '.join(map(str, merged)) or '（无）'}"
        )
    return f"牛牛 {bot_id} 已在库中，指定号主均已在 admins 中。当前号主：{', '.join(map(str, merged)) or '（无）'}"
