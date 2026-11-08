"""群消息跨部署抢占入口。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.logging import log_rate_limited
from pallas.core.platform.federate.config import (
    federate_ingress_active,
    federate_ingress_bypass_unified,
)
from pallas.core.platform.federate.deployment import load_or_create_deployment_id
from pallas.core.platform.ingress.fast_path import run_gate_blocking
from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms
from pallas.core.platform.shard import context as shard_ctx

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

from nonebot import logger

from pallas.core.platform.federate.dedup import try_claim_cross_federate_message
from pallas.core.platform.federate.ingress_audit import record_federate_ingress_audit
from pallas.core.platform.multi_bot.dedup import cross_bot_message_signature

FEDERATE_INGRESS_CLAIM_PLUGIN = "federate_ingress"
FEDERATE_INGRESS_V2_CLAIM_PLUGIN = "federate_ingress_v2"
_WIN_CACHE_MAX = 20_000
_CLAIM_DECISION_MAX = 4_096
_CANDIDATE_WAIT_SEC = 0.15
_win_cache: dict[tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str], float] = {}
_inflight_claims: dict[
    tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str],
    asyncio.Future[bool],
] = {}
_claim_decisions: dict[tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str], tuple[float, bool]] = {}
_win_lock = asyncio.Lock()


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = repo_env_raw_value(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return min(maximum, max(minimum, value))


def win_cache_ttl_sec() -> float:
    """进程内胜出缓存 TTL；30s 覆盖同一条消息的重复投递。"""
    return _env_float("PALLAS_FEDERATE_WIN_CACHE_SEC", 30.0, minimum=1.0, maximum=300.0)


def redis_claim_timeout_sec() -> float:
    """协调 Redis claim 的等待上限；超时按 fail-open 策略处理。"""
    return _env_float("PALLAS_FEDERATE_REDIS_CLAIM_TIMEOUT_SEC", 3.0, minimum=0.05, maximum=10.0)


def claim_decision_ttl_sec() -> float:
    """超时/错误决策的记忆时长，供同签名的重复消息跟随，不再各自重试。"""
    return min(60.0, win_cache_ttl_sec())


def _remember_claim_decision(
    cache_key: tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str],
    *,
    allow: bool,
) -> None:
    """记住本次超时/错误结论；重复消息一律判负，避免同一进程双处理。"""
    now = time.monotonic()
    _claim_decisions[cache_key] = (now + claim_decision_ttl_sec(), allow)
    if len(_claim_decisions) > _CLAIM_DECISION_MAX:
        stale = [key for key, (exp, _allow) in _claim_decisions.items() if now >= exp]
        for key in stale:
            _claim_decisions.pop(key, None)
        if len(_claim_decisions) > _CLAIM_DECISION_MAX:
            _claim_decisions.clear()


def _cached_claim_decision(
    cache_key: tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str],
) -> bool | None:
    hit = _claim_decisions.get(cache_key)
    if hit is None:
        return None
    exp, allow = hit
    if time.monotonic() >= exp:
        _claim_decisions.pop(cache_key, None)
        return None
    return allow


def reset_federate_ingress_win_cache_for_tests() -> None:
    global _win_lock
    _win_cache.clear()
    _inflight_claims.clear()
    _claim_decisions.clear()
    _win_lock = asyncio.Lock()


def bypass_federate_ingress_for_current_mode() -> bool:
    return federate_ingress_bypass_unified() and not shard_ctx.sharding_active()


def federate_claim_fail_open(*, command_traffic: bool) -> bool:
    """协调 Redis 超时/报错后是否放行本条消息。

    命令默认 fail-closed：多个部署同时执行有副作用的命令代价更大；
    闲聊默认 fail-open：丢一条比把整条入站链路卡住好。
    ``PALLAS_FEDERATE_CLAIM_FAIL_OPEN`` 显式设置时统一覆盖两种流量。
    """
    raw = repo_env_raw_value("PALLAS_FEDERATE_CLAIM_FAIL_OPEN")
    if raw is None:
        return not command_traffic
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def federate_ingress_cached_win(
    event: GroupMessageEvent,
    *,
    plugin: str = FEDERATE_INGRESS_CLAIM_PLUGIN,
    include_message_time: bool = True,
    plain: str | None = None,
    body: str | None = None,
) -> bool:
    """本进程是否已缓存赢得联邦 ingress。"""
    if bypass_federate_ingress_for_current_mode():
        return True
    if not federate_ingress_active():
        return True
    plain = (plain if plain is not None else event.get_plaintext() or "").strip()
    body = body if body is not None else (plain or event.raw_message)
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return False
    sig = cross_bot_message_signature(
        int(event.group_id),
        int(event.user_id),
        body,
        event.time,
        use_plaintext=True,
        include_message_time=include_message_time,
    )
    cache_key = (plugin, sig, deployment_id)
    now = time.monotonic()
    exp = _win_cache.get(cache_key)
    return exp is not None and now < exp


async def claim_federate_group_message_ingress(
    event: GroupMessageEvent,
    *,
    plugin: str = FEDERATE_INGRESS_CLAIM_PLUGIN,
    include_message_time: bool = True,
    plain: str | None = None,
    body: str | None = None,
    candidate_capability: str | None = None,
    candidate_bot_id: int | None = None,
    candidate_wait: bool = False,
    command_traffic: bool = False,
) -> bool:
    """未启用联邦 ingress 或本 deployment 抢占成功时返回 True。"""
    timer = SlowPathTimer(
        "federate_ingress",
        threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_FEDERATE_INGRESS_MS", 12.0),
        log_level="debug",
    )
    if bypass_federate_ingress_for_current_mode():
        timer.finish(outcome="unified_bypass")
        return True
    if not federate_ingress_active():
        timer.finish(outcome="disabled")
        return True
    plain = (plain if plain is not None else event.get_plaintext() or "").strip()
    body = body if body is not None else (plain or event.raw_message)
    from pallas.core.platform.federate import candidates

    if candidate_capability and candidate_bot_id is not None:
        record_federate_ingress_audit(capability=candidate_capability, outcome="eligible")
        registered = await run_gate_blocking(
            candidates.register_federate_ingress_candidate_sync,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
            body=body,
            message_time=int(event.time),
            capability=candidate_capability,
            bot_id=int(candidate_bot_id),
        )
        if not registered:
            record_federate_ingress_audit(capability=candidate_capability, outcome="candidate_registration_failed")
            timer.finish(
                outcome="candidate_registration_failed",
                group_id=int(event.group_id),
                user_id=int(event.user_id),
            )
            return False
        record_federate_ingress_audit(capability=candidate_capability, outcome="candidate_registered")
        await asyncio.sleep(_CANDIDATE_WAIT_SEC)
        candidate_ids = await run_gate_blocking(
            candidates.read_federate_ingress_candidate_bot_ids_sync,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
            body=body,
            message_time=int(event.time),
            capability="",
        )
        if candidate_ids and int(candidate_bot_id) != min(candidate_ids):
            record_federate_ingress_audit(capability=candidate_capability, outcome="candidate_yield")
            timer.finish(outcome="candidate_yield", group_id=int(event.group_id), user_id=int(event.user_id))
            return False
        plugin = FEDERATE_INGRESS_V2_CLAIM_PLUGIN
    elif candidate_wait:
        candidate_ids = await run_gate_blocking(
            candidates.read_federate_ingress_candidate_bot_ids_sync,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
            body=body,
            message_time=int(event.time),
            capability="",
        )
        if candidate_ids:
            record_federate_ingress_audit(capability=None, outcome="candidate_yield")
            timer.finish(outcome="candidate_yield", group_id=int(event.group_id), user_id=int(event.user_id))
            return False
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        timer.finish(outcome="missing_deployment_id", group_id=int(event.group_id), user_id=int(event.user_id))
        return False
    sig = cross_bot_message_signature(
        int(event.group_id),
        int(event.user_id),
        body,
        event.time,
        use_plaintext=True,
        include_message_time=include_message_time,
    )
    cache_key = (plugin, sig, deployment_id)
    cached_decision = _cached_claim_decision(cache_key)
    if cached_decision is not None:
        timer.finish(
            outcome="cached_claim_decision",
            cache_hit=True,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
        )
        return cached_decision
    now = time.monotonic()
    wait_for: asyncio.Future[bool] | None = None
    claim_owner = False
    async with _win_lock:
        exp = _win_cache.get(cache_key)
        if exp is not None and now < exp:
            timer.mark("cache_hit")
            timer.finish(outcome="cached_win", cache_hit=True, group_id=int(event.group_id), user_id=int(event.user_id))
            return True
        inflight = _inflight_claims.get(cache_key)
        if inflight is not None:
            wait_for = inflight
        else:
            wait_for = asyncio.get_running_loop().create_future()
            _inflight_claims[cache_key] = wait_for
            claim_owner = True
        if len(_win_cache) > _WIN_CACHE_MAX:
            stale = [k for k, e in _win_cache.items() if now >= e]
            for k in stale:
                _win_cache.pop(k, None)
            if len(_win_cache) > _WIN_CACHE_MAX:
                _win_cache.clear()

    if not claim_owner:
        try:
            won = await asyncio.wait_for(asyncio.shield(wait_for), timeout=redis_claim_timeout_sec())
        except TimeoutError:
            timer.finish(
                outcome="claim_timeout",
                cache_hit=False,
                shared_result=True,
                group_id=int(event.group_id),
                user_id=int(event.user_id),
            )
            record_federate_ingress_audit(capability=candidate_capability, outcome="claim_timeout")
            return False
        timer.mark("inflight_wait")
        timer.finish(
            outcome="won" if won else "lost",
            cache_hit=False,
            shared_result=True,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
        )
        return bool(won)

    try:
        won = await asyncio.wait_for(
            try_claim_cross_federate_message(
                plugin,
                int(event.group_id),
                int(event.user_id),
                body,
                event.time,
                deployment_id,
                use_plaintext=True,
                include_message_time=include_message_time,
            ),
            timeout=redis_claim_timeout_sec(),
        )
    except TimeoutError:
        async with _win_lock:
            if _inflight_claims.get(cache_key) is wait_for:
                _inflight_claims.pop(cache_key)
        if not wait_for.done():
            # 同进程的重复事件跟着本条走：本条放行时它们仍判负，避免一次抖动变成本地双处理。
            wait_for.set_result(False)
        fail_open = federate_claim_fail_open(command_traffic=command_traffic)
        _remember_claim_decision(cache_key, allow=False)
        timer.finish(
            outcome="claim_timeout_open" if fail_open else "claim_timeout",
            cache_hit=False,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
        )
        record_federate_ingress_audit(
            capability=candidate_capability,
            outcome="claim_timeout_open" if fail_open else "claim_timeout",
        )
        return fail_open
    except BaseException as exc:
        async with _win_lock:
            if _inflight_claims.get(cache_key) is wait_for:
                _inflight_claims.pop(cache_key)
        if not wait_for.done():
            if isinstance(exc, asyncio.CancelledError):
                wait_for.cancel()
            else:
                wait_for.set_exception(exc)
                wait_for.exception()
        raise

    if won is None:
        # 协调端明确报错（不是竞争失败）：与超时同策略，命令保持拒绝。
        async with _win_lock:
            if _inflight_claims.get(cache_key) is wait_for:
                _inflight_claims.pop(cache_key)
        if not wait_for.done():
            wait_for.set_result(False)
        fail_open = federate_claim_fail_open(command_traffic=command_traffic)
        _remember_claim_decision(cache_key, allow=False)
        timer.finish(
            outcome="claim_error_open" if fail_open else "claim_error",
            cache_hit=False,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
        )
        record_federate_ingress_audit(
            capability=candidate_capability,
            outcome="claim_error_open" if fail_open else "claim_error",
        )
        log_rate_limited(
            logger,
            "debug",
            "federate_claim_error",
            "联邦 ingress 协调端报错，按 [{}] 处理：group [{}]",
            "fail-open" if fail_open else "fail-closed",
            int(event.group_id),
        )
        return fail_open

    timer.mark("redis_claim")
    async with _win_lock:
        if _inflight_claims.get(cache_key) is wait_for:
            if won:
                _win_cache[cache_key] = time.monotonic() + win_cache_ttl_sec()
            _inflight_claims.pop(cache_key)
    if not wait_for.done():
        wait_for.set_result(won)
    timer.finish(
        outcome="won" if won else "lost",
        cache_hit=False,
        group_id=int(event.group_id),
        user_id=int(event.user_id),
    )
    record_federate_ingress_audit(capability=candidate_capability, outcome="winner" if won else "lost")
    return won
