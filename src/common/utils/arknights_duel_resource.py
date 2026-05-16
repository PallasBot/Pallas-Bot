"""决斗泰拉资源：缺表/缺头像时自动拉取（类似 ensure_voices）。"""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003

import httpx
from nonebot import logger

from src.common.arknights.duel_sync import (
    AVATAR_URL_TEMPLATE,
    CHAR_URL,
    MIN_AVATAR_BYTES,
    OPERATORS_JSON,
    SKILL_URL,
    avatar_local_path,
    build_operators_payload,
    count_valid_avatars,
    download_avatar_sync,
    is_avatar_file_valid,
    load_operators_payload,
    operator_ids_from_payload,
    write_operators_json,
)

_json_lock = asyncio.Lock()
_bulk_avatar_lock = asyncio.Lock()
_avatar_locks: dict[str, asyncio.Lock] = {}
_background_sync_task: asyncio.Task[None] | None = None


def _avatar_lock(char_id: str) -> asyncio.Lock:
    if char_id not in _avatar_locks:
        _avatar_locks[char_id] = asyncio.Lock()
    return _avatar_locks[char_id]


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict:
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        msg = f"expected JSON object from {url}"
        raise TypeError(msg)
    return data


async def _download_avatar_async(client: httpx.AsyncClient, char_id: str, dest: Path) -> bool:
    url = AVATAR_URL_TEMPLATE.format(char_id=char_id)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content
    except (httpx.HTTPError, OSError) as err:
        logger.debug(f"ark avatar download fail {char_id}: {err}")
        return False
    if len(data) < MIN_AVATAR_BYTES:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(dest.write_bytes, data)
    return True


async def sync_operators_json_async() -> bool:
    timeout = httpx.Timeout(120.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        char_table = await _fetch_json(client, CHAR_URL)
        skill_table = await _fetch_json(client, SKILL_URL)
    payload = build_operators_payload(char_table, skill_table)
    await asyncio.to_thread(write_operators_json, payload)
    logger.info(f"arknights duel: wrote {OPERATORS_JSON} ({payload.get('count', 0)} operators)")
    return True


def operators_json_ready() -> bool:
    payload = load_operators_payload()
    if not payload:
        return False
    return int(payload.get("count") or 0) > 0 and bool(operator_ids_from_payload(payload))


async def ensure_operators_json() -> bool:
    if operators_json_ready():
        return True
    async with _json_lock:
        if operators_json_ready():
            return True
        try:
            return await sync_operators_json_async()
        except Exception as err:
            logger.error(f"arknights duel: sync operators json failed: {err}")
            return False


async def sync_missing_avatars_async(
    operator_ids: list[str],
    *,
    missing_only: bool = True,
    concurrency: int = 8,
) -> tuple[int, int]:
    pending = [cid for cid in operator_ids if not (missing_only and is_avatar_file_valid(avatar_local_path(cid)))]
    if not pending:
        return 0, 0

    sem = asyncio.Semaphore(max(1, concurrency))
    ok = 0

    async def one(cid: str) -> bool:
        async with sem:
            dest = avatar_local_path(cid)
            timeout = httpx.Timeout(60.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                return await _download_avatar_async(client, cid, dest)

    results = await asyncio.gather(*(one(cid) for cid in pending), return_exceptions=True)
    for item in results:
        if item is True:
            ok += 1
    return ok, len(pending)


async def ensure_duel_avatars_bulk(
    *,
    min_ratio: float = 0.85,
) -> bool:
    """批量补全缺失头像（启动可选，约百张图）。"""
    payload = load_operators_payload()
    if not payload:
        return False
    ids = operator_ids_from_payload(payload)
    if not ids:
        return False
    have = count_valid_avatars(ids)
    if have >= len(ids) * min_ratio:
        return True

    async with _bulk_avatar_lock:
        have = count_valid_avatars(ids)
        if have >= len(ids) * min_ratio:
            return True
        logger.info(f"arknights duel: avatars {have}/{len(ids)}, downloading missing ...")
        ok, tried = await sync_missing_avatars_async(ids, missing_only=True)
        logger.info(f"arknights duel: avatar sync done ok={ok} tried={tried}")
        return (have + ok) >= len(ids) * min_ratio


async def ensure_duel_avatar(char_id: str, *, allow_download: bool = True) -> Path | None:
    """返回本地头像路径；允许时按需下载单张。"""
    cid = (char_id or "").strip()
    if not cid:
        return None
    dest = avatar_local_path(cid)
    if is_avatar_file_valid(dest):
        return dest
    if not allow_download:
        return None

    async with _avatar_lock(cid):
        if is_avatar_file_valid(dest):
            return dest
        timeout = httpx.Timeout(60.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                ok = await _download_avatar_async(client, cid, dest)
        except Exception as err:
            logger.warning(f"arknights duel: avatar {cid} download error: {err}")
            ok = False
        if not ok:
            ok = await asyncio.to_thread(download_avatar_sync, cid, dest)
        return dest if ok and is_avatar_file_valid(dest) else None


async def ensure_arknights_duel_resources(
    *,
    sync_json: bool = True,
    bulk_avatars: bool = False,
) -> bool:
    """缺 JSON 则拉表；bulk_avatars 为 True 时批量补头像。"""
    json_ok = True
    if sync_json:
        json_ok = await ensure_operators_json()
    if bulk_avatars and json_ok:
        await ensure_duel_avatars_bulk()
    return json_ok


def needs_background_arknights_sync(*, sync_json: bool, bulk_avatars: bool) -> bool:
    """是否需要在启动后后台拉取（表已齐且未开批量头像则跳过）。"""
    if bulk_avatars:
        return True
    return sync_json and not operators_json_ready()


async def _run_background_arknights_sync(*, sync_json: bool, bulk_avatars: bool) -> None:
    try:
        logger.info("arknights duel: background resource sync started")
        ok = await ensure_arknights_duel_resources(sync_json=sync_json, bulk_avatars=bulk_avatars)
        if ok and sync_json:
            from src.plugins.duel.arknights_ops import reload_operators_cache

            reload_operators_cache()
        logger.info(f"arknights duel: background resource sync finished ok={ok}")
    except Exception as err:
        logger.error(f"arknights duel: background resource sync failed: {err}")


def schedule_arknights_duel_resource_sync(
    *,
    sync_json: bool = True,
    bulk_avatars: bool = False,
) -> None:
    """在事件循环中后台同步，不阻塞 NoneBot 启动。"""
    global _background_sync_task
    if not needs_background_arknights_sync(sync_json=sync_json, bulk_avatars=bulk_avatars):
        return
    if _background_sync_task is not None and not _background_sync_task.done():
        logger.debug("arknights duel: background sync already running, skip")
        return
    loop = asyncio.get_running_loop()
    _background_sync_task = loop.create_task(
        _run_background_arknights_sync(sync_json=sync_json, bulk_avatars=bulk_avatars),
        name="arknights_duel_resource_sync",
    )
