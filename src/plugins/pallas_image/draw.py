import asyncio
import re

import httpx
from nonebot import logger, on_command
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
)
from nonebot.exception import FinishedException
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from src.common.cmd_perm import group_message_permission_for_command
from src.common.config import GroupConfig
from src.common.multi_bot.group import (
    claim_group_handler,
    try_begin_group_owned_gate,
)
from src.common.utils.http_msg import PALLAS_VAGUE_REPLY

from .config import ImageApiBackend, active_image_gen_settings, image_gen_config
from .draw_attempts import (
    DrawDeadline,
    DrawTotalTimeoutError,
    finish_draw_failure,
    http_status_edits_unsupported,
    run_backend_param_attempts,
)
from .draw_usage_store import pallas_draw_usage_today
from .image_api import (
    CffiRequestsError,
    download_reference_images,
    generations_payload,
    image_edits_endpoint,
    image_gen_auth_headers_json,
    image_gen_endpoint,
    message_at_user,
    post_edits_with_transport,
    post_generations_with_transport,
    request_timeout_for_deadline,
)
from .image_request_options import ImageGenRequestOptions
from .runtime_state import acquire_draw_pending_slot, release_draw_pending_slot

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


def extract_at_user_ids(msg: Message) -> list[int]:
    """从消息中提取所有 at 段的用户 ID。"""
    ids: list[int] = []
    for seg in msg:
        if seg.type == "at":
            uid = seg.data.get("qq")
            if uid is not None:
                try:
                    ids.append(int(uid))
                except (TypeError, ValueError):
                    pass
    return ids


_AT_QQ_RE = re.compile(r"@(\d{5,12})")


def extract_at_qq_from_text(text: str) -> tuple[list[int], str]:
    """从纯文本中提取 @QQ号，返回 (QQ号列表, 去除 @QQ 后的文本)。
    为避免直接删除 @QQ 导致相邻词语黏连（如 foo@123bar -> foobar），
    这里先用空格替换 @QQ，再对连续空白做一次折叠。
    """
    ids = [int(m.group(1)) for m in _AT_QQ_RE.finditer(text)]
    # 先用空格替换所有 @QQ，再将多余空白折叠为单个空格
    cleaned = _AT_QQ_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return ids, cleaned


def qq_avatar_url(user_id: int) -> str:
    """构造 QQ 头像 URL（用于作为参考图）。"""
    return f"https://q.qlogo.cn/g?b=qq&nk={user_id}&s=0"


def image_backends_with_endpoint(
    backends: list[ImageApiBackend],
    endpoint_fn,
) -> list[ImageApiBackend]:
    return [b for b in backends if endpoint_fn(b)]


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


async def draw_group_cooldown_ready(group_id: int) -> bool:
    """仅检查群冷却是否已过，不扣减。"""
    seconds = image_gen_config.draw_command_cooldown
    if seconds <= 0:
        return True
    gconf = GroupConfig(group_id, cooldown=seconds)
    return await gconf.is_cooldown(PALLAS_DRAW_COOLDOWN_KEY)


async def consume_draw_group_cooldown(group_id: int) -> None:
    """真正开始画画时扣减群冷却。"""
    seconds = image_gen_config.draw_command_cooldown
    if seconds <= 0:
        return
    gconf = GroupConfig(group_id, cooldown=seconds)
    await gconf.refresh_cooldown(PALLAS_DRAW_COOLDOWN_KEY)


async def refund_draw_group_cooldown(group_id: int) -> None:
    """画画未成功出图时退还群冷却。"""
    seconds = image_gen_config.draw_command_cooldown
    if seconds <= 0:
        return
    gconf = GroupConfig(group_id, cooldown=seconds)
    await gconf.reset_cooldown(PALLAS_DRAW_COOLDOWN_KEY)
    logger.info(f"pallas_image draw cooldown refunded group={group_id}")


pallas_draw = on_command(
    "牛牛画画",
    priority=image_gen_config.min_priority,
    block=True,
    permission=group_message_permission_for_command("pallas_image.draw"),
)


@pallas_draw.handle()
async def pallas_draw_handle(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):  # noqa: B008
    group_id = event.group_id
    user_id = event.user_id

    if not draw_group_allowed(group_id):
        return

    bot_id = int(event.self_id)
    if not await claim_group_handler("pallas_image", event, bot_id):
        return

    if not await draw_group_cooldown_ready(group_id):
        return

    backends = active_image_gen_settings().api_backends()
    if not backends or not any((b.model or "").strip() for b in backends):
        await pallas_draw.finish(
            message_at_user(
                user_id,
                "牛牛画画未配置：请设置 pallas_image 的 base_url、api_key、model，或配置 api_backends",
            )
        )

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

    # 如果没有图片参考，尝试用 @ 或回复对象的头像作为参考图
    if not ref_urls:
        # 合并 at 段和纯文本 @QQ 号
        at_ids = extract_at_user_ids(args)
        text_qq_ids, cleaned_text = extract_at_qq_from_text(text)
        all_at_ids = at_ids + text_qq_ids
        if text_qq_ids:
            text = cleaned_text  # 从提示词中去掉 @QQ 号

        avatar_user_id: int | None = None
        if all_at_ids:
            # 取第一个不是 bot 自己的 @ 用户
            bot_self = int(event.self_id)
            for aid in all_at_ids:
                if aid != bot_self:
                    avatar_user_id = aid
                    break
        if avatar_user_id is None and event.reply and event.reply.sender:
            reply_uid = event.reply.sender.user_id
            if reply_uid != int(event.self_id):
                avatar_user_id = reply_uid
        if avatar_user_id is not None:
            ref_urls.append(qq_avatar_url(avatar_user_id))

    if not text and not ref_urls:
        await pallas_draw.finish(
            message_at_user(
                user_id,
                "请说明想画什么，例如：牛牛画画 一只穿斗篷的羊。\n"
                "也可附带一张或多张参考图"
                "或回复一条带图的消息后再发「牛牛画画」 做图生图。",
            )
        )

    if not await acquire_draw_pending_slot():
        await pallas_draw.finish(
            message_at_user(user_id, "牛牛正在给其他小伙伴画画，请稍后再试。"),
        )

    cheer_gate = image_gen_config.draw_command_cooldown
    if not await try_begin_group_owned_gate("pallas_image", group_id, bot_id, gate_sec=cheer_gate):
        return
    await consume_draw_group_cooldown(group_id)

    await pallas_draw.send("欢呼吧！")
    asyncio.create_task(
        run_pallas_draw_queued(
            pallas_draw,
            int(event.self_id),
            usage_key,
            count_usage,
            user_id,
            text,
            ref_urls,
        ),
        name=f"pallas_draw:{group_id}:{user_id}",
    )


async def run_pallas_draw_queued(
    matcher,
    bot_id: int,
    usage_key: tuple[int, int],
    count_usage: bool,
    user_id: int,
    text: str,
    ref_urls: list[str],
) -> None:
    group_id, _ = usage_key
    image_sent = False
    try:
        async with get_pallas_draw_user_lock(group_id, user_id):
            limit_n = image_gen_config.draw_per_user_limit
            if count_usage and pallas_draw_usage_today(usage_key) >= limit_n:
                await matcher.send(message_at_user(user_id, f"你在本群今日的画画次数已达上限（{limit_n}）。"))
                return
            image_sent = await pallas_draw_execute(matcher, bot_id, usage_key, count_usage, user_id, text, ref_urls)
    except FinishedException:
        raise
    except DrawTotalTimeoutError:
        logger.warning(f"bot [{bot_id}] pallas_image draw total timeout in group [{group_id}]")
        try:
            await matcher.finish(message_at_user(user_id, PALLAS_VAGUE_REPLY))
        except FinishedException:
            raise
        except Exception as send_err:
            logger.warning(f"bot [{bot_id}] pallas_image draw timeout reply failed: {send_err}")
    except Exception as e:
        logger.exception(f"bot [{bot_id}] pallas_image queued draw failed in group [{group_id}]: {e}")
        try:
            await matcher.send(message_at_user(user_id, PALLAS_VAGUE_REPLY))
        except FinishedException:
            raise
        except Exception as send_err:
            logger.warning(f"bot [{bot_id}] pallas_image draw failure reply failed: {send_err}")
    finally:
        if not image_sent:
            await refund_draw_group_cooldown(group_id)
        await release_draw_pending_slot()


async def pallas_draw_execute(
    matcher,
    bot_id: int,
    usage_key: tuple[int, int],
    count_usage: bool,
    user_id: int,
    text: str,
    ref_urls: list[str],
) -> bool:
    cfg = image_gen_config
    group_id = usage_key[0]
    backends = cfg.api_backends()
    default_prompt = (cfg.default_edit_prompt or "生成图像").strip()
    if cfg.merge_reference_urls_into_prompt:
        gen_prompt = " ".join([p for p in [text, *ref_urls] if p])
    elif text.strip():
        gen_prompt = text.strip()
    elif ref_urls:
        gen_prompt = default_prompt
    else:
        gen_prompt = default_prompt

    deadline = DrawDeadline(cfg.draw_total_timeout)
    last_body: list[str] = [""]
    last_status: list[int] = [0]

    req_timeout = cfg.request_timeout
    client_timeout = httpx.Timeout(connect=30.0, read=req_timeout, write=req_timeout, pool=req_timeout)
    limits = httpx.Limits(max_connections=max(4, cfg.max_concurrency * 2))

    try:
        async with httpx.AsyncClient(timeout=client_timeout, trust_env=True, limits=limits) as http_client:
            if ref_urls and cfg.use_edits_for_reference_images:
                ref_dl_timeout = min(
                    cfg.ref_download_timeout,
                    max(1.0, deadline.remaining_seconds()),
                )
                blobs = await download_reference_images(
                    http_client,
                    ref_urls,
                    download_timeout=ref_dl_timeout,
                )
                if blobs:
                    if len(ref_urls) > len(blobs):
                        logger.warning(
                            f"bot [{bot_id}] pallas_image ref download partial in group [{group_id}]: "
                            f"requested {len(ref_urls)} refs, got {len(blobs)} blobs",
                        )
                    edit_prompt = text.strip() or default_prompt
                    edit_backends = image_backends_with_endpoint(backends, image_edits_endpoint)
                    edits_abort = [False]

                    async def post_edits(backend: ImageApiBackend, req_opts: ImageGenRequestOptions) -> tuple[int, str]:
                        return await post_edits_with_transport(
                            http_client,
                            blobs,
                            edit_prompt,
                            backend,
                            options=req_opts,
                            req_timeout_cap=request_timeout_for_deadline(deadline.remaining_seconds()),
                        )

                    if await run_backend_param_attempts(
                        matcher,
                        http_client,
                        bot_id,
                        group_id,
                        user_id,
                        usage_key,
                        count_usage,
                        deadline,
                        "edits",
                        edit_backends,
                        with_ref_urls=False,
                        post_request=post_edits,
                        last_body_holder=last_body,
                        last_status_holder=last_status,
                        edits_abort_holder=edits_abort,
                    ):
                        return True
                    if edits_abort[0] or http_status_edits_unsupported(last_status[0]):
                        logger.info(
                            f"bot [{bot_id}] pallas_image edits unsupported status={last_status[0]} "
                            f"in group [{group_id}], fallback to generations",
                        )
                    else:
                        logger.warning(
                            f"bot [{bot_id}] pallas_image edits exhausted in group [{group_id}], "
                            f"fallback to generations",
                        )

            payload_model = backends[0].model if backends else cfg.model
            gen_backends = image_backends_with_endpoint(backends, image_gen_endpoint)

            async def post_generations(backend: ImageApiBackend, req_opts: ImageGenRequestOptions) -> tuple[int, str]:
                gen_ep = image_gen_endpoint(backend)
                headers = image_gen_auth_headers_json(backend)
                payload = generations_payload(
                    gen_prompt,
                    ref_urls,
                    model=backend.model or payload_model,
                    backend=backend,
                    options=req_opts,
                )
                return await post_generations_with_transport(
                    http_client,
                    gen_ep,
                    headers,
                    payload,
                    req_timeout_cap=request_timeout_for_deadline(deadline.remaining_seconds()),
                )

            if await run_backend_param_attempts(
                matcher,
                http_client,
                bot_id,
                group_id,
                user_id,
                usage_key,
                count_usage,
                deadline,
                "generations",
                gen_backends,
                with_ref_urls=bool(ref_urls),
                post_request=post_generations,
                last_body_holder=last_body,
                last_status_holder=last_status,
            ):
                return True

            logger.error(
                f"bot [{bot_id}] pallas_image generations exhausted backends in group [{group_id}]",
            )
            await finish_draw_failure(matcher, user_id, last_body[0])
            return False
    except FinishedException:
        raise
    except DrawTotalTimeoutError:
        raise
    except httpx.TimeoutException:
        logger.error(f"bot [{bot_id}] pallas_image api timeout in group [{group_id}] after {req_timeout}s")
        await matcher.finish(PALLAS_VAGUE_REPLY)
    except httpx.ConnectError as e:
        logger.error(f"bot [{bot_id}] pallas_image api connect error in group [{group_id}]: {e}")
        await matcher.finish(PALLAS_VAGUE_REPLY)
    except CffiRequestsError as e:
        logger.error(f"bot [{bot_id}] pallas_image curl_cffi error in group [{group_id}]: {e}")
        await matcher.finish(PALLAS_VAGUE_REPLY)
    except RuntimeError as e:
        logger.error(f"bot [{bot_id}] pallas_image transport runtime error in group [{group_id}]: {e}")
        await matcher.finish(PALLAS_VAGUE_REPLY)
    except httpx.HTTPError as e:
        logger.error(f"bot [{bot_id}] pallas_image httpx error in group [{group_id}]: {e}")
        await matcher.finish(PALLAS_VAGUE_REPLY)
    except Exception as e:
        logger.exception(f"bot [{bot_id}] pallas_image api exception in group [{group_id}]: {e}")
        await matcher.finish(PALLAS_VAGUE_REPLY)
    return False
