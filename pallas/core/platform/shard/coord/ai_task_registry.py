"""AI 异步任务持久化登记；分片模式额外记录 callback 所属 worker 路由。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from typing import Any

from pallas.core.platform.coord.redis_logging import log_coord_redis_failure
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.registry import get_shard_registry, worker_port_for_shard
from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.store import assign_bot_to_shard
from pallas.core.platform.shard.worker_port import current_worker_port

_DEFAULT_TTL_SEC = 86400.0
_KEY_PREFIX = "pallas:ai_task:"
_TERMINAL_PREFIX = "pallas:ai_task_done:"

# 原子登记：单次调用内完成终态检查、绑定/受保护内容比较与创建，消除检查与写入之间的窗口。
_REGISTER_SCRIPT = """
-- pallas:ai_task:register
local function s(v) if v == nil then return '' end return tostring(v) end
if redis.call('EXISTS', KEYS[1]) == 1 then return 'conflict' end
local existing = redis.call('GET', KEYS[2])
if existing then
  local ok, dec = pcall(cjson.decode, existing)
  if not ok or type(dec) ~= 'table' then return 'conflict' end
  if s(dec['_binding_sig']) ~= ARGV[3] or s(dec['_content_sig']) ~= ARGV[4] then return 'conflict' end
  return 'ok'
end
redis.call('SET', KEYS[2], ARGV[1], 'EX', tonumber(ARGV[2]))
return 'ok'
"""

# 原子领取：取记录、删除键、写终态一步完成；无记录时不触碰任何键，避免旧领取者清理新终态。
_CLAIM_SCRIPT = """
-- pallas:ai_task:claim
local raw = redis.call('GET', KEYS[1])
if not raw then return nil end
redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[1]))
redis.call('DEL', KEYS[1])
return raw
"""

# 原子取消：写终态并删除待处理键，结束 ID 在 TTL 内不得复活。
_TERMINAL_REMOVE_SCRIPT = """
-- pallas:ai_task:terminal_remove
redis.call('SET', KEYS[1], '1', 'EX', tonumber(ARGV[1]))
redis.call('DEL', KEYS[2])
return 1
"""

_PROTECTED_FIELDS = ("song_id", "command_source_segments")


class AiTaskRedisError(RuntimeError):
    """Redis 协调不可用；调用方应返回可重试错误而非静默本地成功。"""


def ai_task_terminal_key(task_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)
    return f"{_TERMINAL_PREFIX}{safe}"


def ai_task_ttl_sec() -> float:
    raw = os.getenv("PALLAS_AI_TASK_TTL_SEC", "").strip()
    try:
        ttl = float(raw) if raw else _DEFAULT_TTL_SEC
    except ValueError:
        ttl = _DEFAULT_TTL_SEC
    return max(600.0, ttl)


def ai_task_redis_key(task_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)
    return f"{_KEY_PREFIX}{safe}"


def normalize_ai_task_status(task_status: Any) -> dict[str, Any] | None:
    """共同登记入口的规范化：主体 ID/类型/有限 start_time；非法返回 None。

    本地与 Redis 使用同一份规范化记录，避免字符串时间等毒化后续本地任务表。
    """
    if not isinstance(task_status, dict):
        return None
    try:
        record = json.loads(json.dumps(task_status, ensure_ascii=False))
    except (TypeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    bot_raw = record.get("bot_id")
    bot_id = "" if bot_raw is None else str(bot_raw).strip()
    if not bot_id.isdigit():
        return None
    raw_start = record.get("start_time")
    if raw_start is None or isinstance(raw_start, bool) or not isinstance(raw_start, (int, float)):
        return None
    start_time = float(raw_start)
    if not math.isfinite(start_time) or start_time <= 0:
        return None
    for key in ("group_id", "user_id"):
        value = record.get(key)
        if value is None:
            continue
        try:
            record[key] = int(value)
        except (TypeError, ValueError):
            return None
    record["bot_id"] = bot_id
    record["task_type"] = str(record.get("task_type") or "").strip()
    record["start_time"] = start_time
    return record


def ai_task_protected_signature(rec: dict[str, Any]) -> str:
    """受保护内容（歌曲绑定/来源消息段）的稳定签名，用于同绑定重试的幂等与冲突判定。"""
    payload = {key: rec.get(key) for key in _PROTECTED_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ai_task_binding_signature(rec: dict[str, Any]) -> str:
    """登记绑定签名；在 Python 侧算好，避免 Lua 浮点 tostring 与 Python str 不一致。"""
    canonical = "\x1f".join(ai_task_binding(rec))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode_redis_text(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def write_ai_task_redis_sync(rec: dict[str, Any], *, ttl_sec: int) -> str:
    """写入登记；返回 ok / conflict / skipped。

    单次原子脚本完成终态检查、已有绑定与受保护内容判定及创建；协调已启用但不可用
    时抛 AiTaskRedisError（调用方映射 503），不得静默降级为成功。
    """
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_task_required

    if not coord_redis_task_required():
        return "skipped"
    client = get_coord_redis_client()
    if client is None:
        raise AiTaskRedisError("coord redis client unavailable")
    task_id = str(rec.get("task_id") or "").strip()
    if not task_id:
        return "conflict"
    ttl = max(60, int(ttl_sec))
    body_rec = dict(rec)
    body_rec["_binding_sig"] = ai_task_binding_signature(rec)
    body_rec["_content_sig"] = ai_task_protected_signature(rec)
    body = json.dumps(body_rec, ensure_ascii=False, separators=(",", ":"))
    try:
        result = client.eval(
            _REGISTER_SCRIPT,
            2,
            ai_task_terminal_key(task_id),
            ai_task_redis_key(task_id),
            body,
            ttl,
            body_rec["_binding_sig"],
            body_rec["_content_sig"],
        )
    except Exception as e:
        log_coord_redis_failure("write_ai_task", e)
        raise AiTaskRedisError("redis register failed") from e
    return "conflict" if _decode_redis_text(result) == "conflict" else "ok"


def ai_task_binding(rec: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """登记绑定键：主体/群/用户/类型/起始时间，用于幂等与冲突判定。"""

    def _s(key: str) -> str:
        value = rec.get(key)
        return "" if value is None else str(value).strip()

    return (_s("bot_id"), _s("group_id"), _s("user_id"), _s("task_type"), _s("start_time"))


def ai_task_is_terminal_sync(task_id: str) -> bool | None:
    """True/False 明确；None 表示协调要求但 Redis 不可用。"""
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_task_required

    if not coord_redis_task_required():
        return False
    client = get_coord_redis_client()
    if client is None:
        return None
    try:
        return client.get(ai_task_terminal_key(task_id)) is not None
    except Exception as e:
        log_coord_redis_failure("read_ai_task_terminal", e)
        return None


def read_ai_task_redis_sync(task_id: str) -> dict[str, Any] | None:
    """非破坏读取待处理登记；未要求协调返回 None，协调不可用抛 AiTaskRedisError。"""
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_task_required

    if not coord_redis_task_required():
        return None
    client = get_coord_redis_client()
    if client is None:
        raise AiTaskRedisError("coord redis client unavailable")
    try:
        raw = client.get(ai_task_redis_key(task_id))
    except Exception as e:
        log_coord_redis_failure("read_ai_task", e)
        raise AiTaskRedisError("redis read failed") from e
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def remove_ai_task_redis_sync(task_id: str) -> None:
    """取消登记：写共享终态并删除待处理键；协调不可用抛 AiTaskRedisError，不静默成功。"""
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_task_required

    if not coord_redis_task_required():
        return
    client = get_coord_redis_client()
    if client is None:
        raise AiTaskRedisError("coord redis client unavailable")
    try:
        client.eval(
            _TERMINAL_REMOVE_SCRIPT,
            2,
            ai_task_terminal_key(task_id),
            ai_task_redis_key(task_id),
            max(60, int(ai_task_ttl_sec())),
        )
    except Exception as e:
        log_coord_redis_failure("remove_ai_task", e)
        raise AiTaskRedisError("redis remove failed") from e


def claim_ai_task_redis_sync(task_id: str) -> dict[str, Any] | None:
    """原子领取 Redis 中的 AI 任务登记；协调不可用时抛 AiTaskRedisError。

    单次原子脚本完成取记录、删除键与写终态：同一 ID 只能被领取一次（at-most-once），
    终态 ID 不得复活；空记录时不触碰任何键，旧领取者不会删除新终态。
    """
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_task_required

    if not coord_redis_task_required():
        return None
    client = get_coord_redis_client()
    if client is None:
        raise AiTaskRedisError("coord redis client unavailable")
    ttl = max(60, int(ai_task_ttl_sec()))
    try:
        raw = client.eval(
            _CLAIM_SCRIPT,
            2,
            ai_task_redis_key(task_id),
            ai_task_terminal_key(task_id),
            ttl,
        )
    except Exception as e:
        log_coord_redis_failure("claim_ai_task", e)
        raise AiTaskRedisError("redis claim failed") from e
    if raw is None:
        return None
    try:
        data = json.loads(_decode_redis_text(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_stale(rec: dict[str, Any]) -> bool:
    start = float(rec.get("start_time") or 0)
    return start <= 0 or (time.time() - start) > ai_task_ttl_sec()


def build_ai_task_record(task_id: str, task_status: dict[str, Any]) -> dict[str, Any] | None:
    record = normalize_ai_task_status(task_status)
    if record is None:
        return None
    record["task_id"] = task_id
    bot_id = record["bot_id"]
    if not shard_ctx.sharding_active():
        return record
    reg = get_shard_registry()
    sid = reg.shard_for_bot(bot_id)
    if sid is not None:
        port = worker_port_for_shard(int(sid), registry=reg)
    else:
        local_port = current_worker_port()
        if local_port is not None:
            sid = int(get_shard_registry_settings().shard_id)
            port = int(local_port)
        else:
            sid = assign_bot_to_shard(bot_id, registry=reg)
            if sid is None:
                return None
            port = worker_port_for_shard(int(sid), registry=reg)
    record.update(shard_id=int(sid), worker_port=int(port))
    return record


def register_ai_task(task_id: str, task_status: dict[str, Any]) -> str:
    from pallas.core.platform.ai_callback.task_types import is_retired_chat_task_type

    if is_retired_chat_task_type(task_status.get("task_type")):
        return "conflict"  # retired chat task types never register new Redis work
    rec = build_ai_task_record(task_id, task_status)
    if rec is None:
        return "conflict"
    ttl = int(ai_task_ttl_sec())
    return write_ai_task_redis_sync(rec, ttl_sec=ttl)


def remove_ai_task(task_id: str) -> None:
    remove_ai_task_redis_sync(task_id)


def get_ai_task_record(task_id: str) -> dict[str, Any] | None:
    """非破坏读取待处理登记：缺失/过期返回 None，且不写终态、不取消该 ID。

    协调要求但读取失败时抛 AiTaskRedisError，交由边界映射 503；不静默降级为「未找到」。
    """
    terminal = ai_task_is_terminal_sync(task_id)
    if terminal is None:
        raise AiTaskRedisError("coord redis unavailable")
    if terminal:
        return None
    rec = read_ai_task_redis_sync(task_id)
    if not rec or _is_stale(rec):
        return None
    return rec


def claim_ai_task_record(task_id: str) -> dict[str, Any] | None:
    """原子领取持久化任务登记；已被领取或过期则返回 None。Redis 不可用抛 AiTaskRedisError。"""
    rec = claim_ai_task_redis_sync(task_id)
    if not rec:
        return None
    if _is_stale(rec):
        return None
    return rec


def resolve_worker_port_for_task(task_id: str) -> int | None:
    """hub 路由用；缺失返回 None，读取失败抛 AiTaskRedisError（边界映射 503）。"""
    rec = get_ai_task_record(task_id)
    if not rec:
        return None
    try:
        return int(rec["worker_port"])
    except (KeyError, TypeError, ValueError):
        return None
