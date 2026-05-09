import asyncio
import time

import httpx
from nonebot import logger, on_command
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    permission,
)
from nonebot.exception import FinishedException
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from src.common.config import GroupConfig
from src.common.utils.http_msg import PALLAS_VAGUE_REPLY, user_failure_reply

from .config import image_gen_config
from .draw_usage_store import bump_pallas_draw_usage, pallas_draw_usage_today
from .image_api import (
    CffiRequestsError,
    bytes_from_image_reference,
    generations_payload,
    image_edits_endpoint,
    image_gen_auth_headers_json,
    image_gen_endpoint,
    message_at_user,
    post_edits_with_transport,
    post_generations_with_transport,
    reply_from_image_api_json,
)
from .runtime_state import image_gen_semaphore

PALLAS_DRAW_COOLDOWN_KEY = "pallas_draw_command"


def extract_image_urls_from_message(msg: Message) -> list[str]:
    urls: list[str] = []
    for seg in msg:
        if seg.type == "image":
            u = seg.data.get("url") or seg.data.get("file") or ""
            if isinstance(u, str) and u.strip():
                urls.append(u.strip())
    return urls


def dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


_MAX_PALLAS_DRAW_USER_LOCKS = 8192
pallas_draw_user_locks: dict[tuple[int, int], asyncio.Lock] = {}


def get_pallas_draw_user_lock(group_id: int, user_id: int) -> asyncio.Lock:
    key = (group_id, user_id)
    if len(pallas_draw_user_locks) > _MAX_PALLAS_DRAW_USER_LOCKS:
        for k in list(pallas_draw_user_locks.keys()):
            if len(pallas_draw_user_locks) <= _MAX_PALLAS_DRAW_USER_LOCKS:
                break
            lock = pallas_draw_user_locks.get(k)
            if lock is not None and not lock.locked():
                del pallas_draw_user_locks[k]
    if key not in pallas_draw_user_locks:
        pallas_draw_user_locks[key] = asyncio.Lock()
    return pallas_draw_user_locks[key]


def draw_group_allowed(group_id: int) -> bool:
    wl = image_gen_config.draw_group_whitelist
    return not wl or group_id in wl


def draw_should_count_usage(group_id: int, user_id: int) -> bool:
    cfg = image_gen_config
    if cfg.draw_per_user_limit <= 0:
        return False
    if group_id in cfg.draw_unlimited_group_ids_set:
        return False
    if user_id in cfg.draw_unlimited_user_ids_set:
        return False
    return True


async def acquire_pallas_draw_group_cooldown(group_id: int) -> bool:
    seconds = image_gen_config.draw_command_cooldown
    if seconds <= 0:
        return True
    gconf = GroupConfig(group_id, cooldown=seconds)
    if not await gconf.is_cooldown(PALLAS_DRAW_COOLDOWN_KEY):
        return False
    await gconf.refresh_cooldown(PALLAS_DRAW_COOLDOWN_KEY)
    return True


pallas_draw = on_command(
    "牛牛画画",
    priority=image_gen_config.min_priority,
    block=True,
    permission=permission.GROUP,
)


@pallas_draw.handle()
async def pallas_draw_handle(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):  # noqa: B008
    group_id = event.group_id
    user_id = event.user_id

    if not draw_group_allowed(group_id):
        return

    if not await acquire_pallas_draw_group_cooldown(group_id):
        return

    if (
        not (image_gen_config.base_url or "").strip()
        or not (image_gen_config.api_key or "").strip()
        or not (image_gen_config.model or "").strip()
    ):
        await pallas_draw.finish(
            message_at_user(
                user_id,
                "牛牛画画未配置：请设置 pallas_image 的 base_url、api_key、model",
            )
        )

    async with get_pallas_draw_user_lock(group_id, user_id):
        usage_key = (group_id, user_id)
        count_usage = draw_should_count_usage(group_id, user_id)
        if await SUPERUSER(bot, event):
            count_usage = False
        limit_n = image_gen_config.draw_per_user_limit
        if count_usage and pallas_draw_usage_today(usage_key) >= limit_n:
            await pallas_draw.finish(message_at_user(user_id, f"你在本群今日的画画次数已达上限（{limit_n}）。"))

        text = args.extract_plain_text().strip()
        ref_urls = dedupe_urls(
            extract_image_urls_from_message(args)
            + (extract_image_urls_from_message(event.reply.message) if event.reply else [])
        )
        if not text and not ref_urls:
            await pallas_draw.finish(
                message_at_user(
                    user_id,
                    "请说明想画什么，例如：牛牛画画 一只穿斗篷的羊。\n"
                    "也可附带一张或多张参考图"
                    "或回复一条带图的消息后再发「牛牛画画」 做图生图。",
                )
            )

        await pallas_draw_execute(pallas_draw, usage_key, count_usage, user_id, text, ref_urls)


async def pallas_draw_execute(
    matcher,
    usage_key: tuple[int, int],
    count_usage: bool,
    user_id: int,
    text: str,
    ref_urls: list[str],
) -> None:
    cfg = image_gen_config
    default_prompt = (cfg.default_edit_prompt or "生成图像").strip()
    if cfg.merge_reference_urls_into_prompt:
        gen_prompt = " ".join([p for p in [text, *ref_urls] if p])
    elif text.strip():
        gen_prompt = text.strip()
    elif ref_urls:
        gen_prompt = default_prompt
    else:
        gen_prompt = default_prompt

    gen_ep = image_gen_endpoint()
    edits_ep = image_edits_endpoint()
    if not gen_ep:
        await matcher.finish(PALLAS_VAGUE_REPLY)

    auth_json_headers = image_gen_auth_headers_json()
    httpx_timeout = httpx.Timeout(cfg.request_timeout)
    await matcher.send("欢呼吧！")
    async with image_gen_semaphore:
        try:
            async with httpx.AsyncClient(timeout=httpx_timeout, trust_env=True) as http_client:
                if ref_urls and cfg.use_edits_for_reference_images and edits_ep:
                    blobs: list[bytes] = []
                    for u in ref_urls:
                        b = await bytes_from_image_reference(http_client, u)
                        if b:
                            blobs.append(b)
                    if blobs:
                        edit_prompt = text.strip() or default_prompt
                        if len(ref_urls) > len(blobs):
                            logger.warning(
                                "部分参考图下载失败：请求 {} 张，实际 {} 张",
                                len(ref_urls),
                                len(blobs),
                            )
                        logger.info(
                            "sending image edits request to: {} ({} images)",
                            edits_ep,
                            len(blobs),
                        )
                        req_started = time.perf_counter()
                        status, body_text = await post_edits_with_transport(blobs, edit_prompt)
                        logger.info(
                            "image edits response: status={}, elapsed_ms={:.0f}, body_len={}, url={}",
                            status,
                            (time.perf_counter() - req_started) * 1000,
                            len(body_text),
                            edits_ep,
                        )
                        if status != 200:
                            logger.error(
                                "image edits failed: status={}, body={}",
                                status,
                                body_text[:2000],
                            )
                            await matcher.finish(message_at_user(user_id, user_failure_reply(body_text)))
                        await reply_from_image_api_json(
                            matcher,
                            http_client,
                            body_text,
                            at_user_id=user_id,
                            persist_draw=(usage_key[0], usage_key[1]),
                        )
                        bump_pallas_draw_usage(usage_key, count_usage)
                        return

                payload = generations_payload(gen_prompt, ref_urls)
                logger.info("sending image generation request to: {}", gen_ep)
                request_started = time.perf_counter()
                status, body_text = await post_generations_with_transport(
                    gen_ep,
                    auth_json_headers,
                    payload,
                )
                logger.info(
                    "image generations response: status={}, elapsed_ms={:.0f}, body_len={}, url={}",
                    status,
                    (time.perf_counter() - request_started) * 1000,
                    len(body_text),
                    gen_ep,
                )
                if status != 200:
                    logger.error(
                        "image generations failed: status={}, body={}",
                        status,
                        body_text[:2000],
                    )
                    await matcher.finish(message_at_user(user_id, user_failure_reply(body_text)))
                await reply_from_image_api_json(
                    matcher,
                    http_client,
                    body_text,
                    at_user_id=user_id,
                    persist_draw=(usage_key[0], usage_key[1]),
                )
                bump_pallas_draw_usage(usage_key, count_usage)
        except FinishedException:
            raise
        except httpx.TimeoutException:
            logger.error("image api timeout: {}s", cfg.request_timeout)
            await matcher.finish(PALLAS_VAGUE_REPLY)
        except httpx.ConnectError as e:
            logger.error("image api connection failed: {}", e)
            await matcher.finish(PALLAS_VAGUE_REPLY)
        except CffiRequestsError as e:
            logger.error("image api curl_cffi failed: {}", e)
            await matcher.finish(PALLAS_VAGUE_REPLY)
        except RuntimeError as e:
            logger.error("image api curl/runtime error: {}", e)
            await matcher.finish(PALLAS_VAGUE_REPLY)
        except httpx.HTTPError as e:
            logger.error("image httpx error: {}", e)
            await matcher.finish(PALLAS_VAGUE_REPLY)
        except Exception as e:
            logger.exception("image api exception: {}", e)
            await matcher.finish(PALLAS_VAGUE_REPLY)
