"""语义风格 v3 实验治理：群日稳定 A/B、exposure 记录与统计熔断。

对照组按 ``bot × group × 北京自然日`` 稳定分桶：同一群当天体验一致，
次日可换桶。熔断只停注入，不停采集；硬错误由各直投通道自行熔断。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import TYPE_CHECKING, Any

from nonebot import get_driver, logger

from pallas.core.foundation.fs_lock import interprocess_file_lock
from pallas.core.foundation.logging import log_rate_limited
from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

# 对照组占比：bucket == 0 为 control。
_CONTROL_BUCKET = 0
_BUCKET_COUNT = 10
# 统计熔断前置：实验至少 200 回合、对照至少 20 回合。
_EXPERIMENT_MIN_SETTLED = 200
_CONTROL_MIN_SETTLED = 20
# 双阈值：负反馈率差 ≥ 3 个百分点且 ≥ 1.5 倍。
_NEGATIVE_RATE_DELTA = 0.03
_NEGATIVE_RATE_RATIO = 1.5
# 被动 outcome 结算：投递后 90 秒窗口、最多看 3 条真人消息。
_OUTCOME_WINDOW_SEC = 90
_OUTCOME_MAX_FOLLOWUPS = 3
_OUTCOME_SETTLE_INTERVAL_SEC = 60
_OUTCOME_MAX_PER_PASS = 200
_SETTLED_REQUEST_ID_LIMIT = 8192

# 高置信负反馈短语：要求回复/提及 Bot 或与目标用户 exposure 时间窗口一致。
_NEGATIVE_PHRASES = (
    "别回",
    "闭嘴",
    "不要说了",
    "答非所问",
    "你在说什么",
    "不是这个",
    "说错了",
    "胡说",
    "没问你",
    "又复读",
    "别说了",
    "别烦",
    "别闹",
    "别吵",
    "别乱叫",
    "别催",
    "少来这套",
    "关你屁事",
    "想得美",
)
_NEGATIVE_PHRASE_RE = re.compile("|".join(re.escape(phrase) for phrase in _NEGATIVE_PHRASES))


def experiment_base_dir() -> Path:
    return plugin_data_dir("pb_webui", create=True) / "repeater_semantic_style"


def exposures_path() -> Path:
    return experiment_base_dir() / "exposures.jsonl"


def experiment_state_path() -> Path:
    return experiment_base_dir() / "experiment_state.json"


def semantic_style_day_key(now: int | None = None) -> str:
    from pallas.product.llm.daily_budget import natural_day_key

    return natural_day_key(now)


def semantic_style_bucket(bot_id: int, group_id: int, now: int | None = None) -> int:
    """群日稳定分桶：同一 bot×群×自然日固定同一桶。"""
    day = semantic_style_day_key(now)
    digest = hashlib.blake2b(f"{int(bot_id)}:{int(group_id)}:{day}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % _BUCKET_COUNT


def semantic_style_in_control(bot_id: int, group_id: int, now: int | None = None) -> bool:
    return semantic_style_bucket(bot_id, group_id, now=now) == _CONTROL_BUCKET


def _load_state() -> dict[str, Any]:
    try:
        raw = json.loads(experiment_state_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = experiment_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def semantic_style_circuit_disabled() -> bool:
    """统计熔断状态：熔断后停注入，但采集继续。"""
    state = _load_state()
    return bool(state.get("circuit_disabled"))


def semantic_channel_circuit_disabled(channel: str) -> bool:
    state = _load_state()
    circuits = state.get("channel_circuits") or {}
    return bool((circuits.get(str(channel)) or {}).get("disabled"))


def trip_semantic_channel_circuit(channel: str, reason: str) -> None:
    with interprocess_file_lock(experiment_state_path().with_suffix(".lock")):
        state = _load_state()
        circuits = state.setdefault("channel_circuits", {})
        circuits[str(channel)] = {
            "disabled": True,
            "reason": str(reason or "hard_error")[:120],
            "tripped_at": int(time.time()),
        }
        _save_state(state)


def reset_semantic_channel_circuit(channel: str) -> None:
    with interprocess_file_lock(experiment_state_path().with_suffix(".lock")):
        state = _load_state()
        circuits = state.get("channel_circuits") or {}
        circuits.pop(str(channel), None)
        if circuits:
            state["channel_circuits"] = circuits
        else:
            state.pop("channel_circuits", None)
        _save_state(state)


def record_semantic_exposure(
    *,
    request_id: str,
    bot_id: int,
    group_id: int,
    user_id: int,
    bucket: int,
    injection_types: list[str],
    source_ids: list[str],
    delivery_source: str,
    bot_message_id: int | None,
    delivered_at: int | None = None,
) -> None:
    """记录一次语义注入/直投的 exposure，供被动 outcome 结算。"""
    if int(bot_id) <= 0 or int(group_id) <= 0:
        return
    now = int(time.time()) if delivered_at is None else int(delivered_at)
    record = {
        "request_id": str(request_id),
        "bot_id": int(bot_id),
        "group_id": int(group_id),
        "user_id": int(user_id),
        "bucket": int(bucket),
        "injection_types": [str(item) for item in injection_types if str(item).strip()],
        "source_ids": [str(item) for item in source_ids if str(item).strip()],
        "delivery_source": str(delivery_source),
        "bot_message_id": int(bot_message_id) if bot_message_id else None,
        "delivered_at": now,
        "settled": False,
    }
    path = exposures_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with interprocess_file_lock(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _load_exposures() -> list[dict[str, Any]]:
    try:
        lines = exposures_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _load_unsettled_exposures() -> list[dict[str, Any]]:
    return [item for item in _load_exposures() if not item.get("settled")]


def _rewrite_exposures(rows: list[dict[str, Any]]) -> None:
    path = exposures_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in rows),
        encoding="utf-8",
    )
    tmp.replace(path)


def mark_exposures_settled(request_ids: set[str]) -> None:
    """把已结算的 exposure 标记为 settled，避免重复统计。"""
    if not request_ids:
        return
    with interprocess_file_lock(exposures_path().with_suffix(".lock")):
        rows = _load_exposures()
        changed = False
        for item in rows:
            if item.get("request_id") in request_ids:
                item["settled"] = True
                changed = True
        if changed:
            _rewrite_exposures(rows)


def record_experiment_outcome(
    *,
    request_id: str,
    bucket: int,
    target_followup: bool,
    negative: bool,
) -> bool:
    """累计一次已结算 exposure 的实验/对照计数。"""
    with interprocess_file_lock(experiment_state_path().with_suffix(".lock")):
        state = _load_state()
        settled_ids = [str(item) for item in state.get("settled_request_ids") or []]
        stable_request_id = str(request_id or "").strip()
        if not stable_request_id or stable_request_id in settled_ids:
            return False
        group = "control" if bucket == _CONTROL_BUCKET else "experiment"
        counts = state.setdefault(group, {})
        counts["settled"] = int(counts.get("settled") or 0) + 1
        if target_followup:
            counts["target_followup"] = int(counts.get("target_followup") or 0) + 1
        if negative:
            counts["negative"] = int(counts.get("negative") or 0) + 1
        state["settled_request_ids"] = [*settled_ids, stable_request_id][-_SETTLED_REQUEST_ID_LIMIT:]
        _save_state(state)
        return True


def maybe_trip_circuit() -> bool:
    """统计熔断：实验/对照达到最小样本后，负反馈率双阈值触发则停注入。"""
    with interprocess_file_lock(experiment_state_path().with_suffix(".lock")):
        state = _load_state()
        if state.get("circuit_disabled"):
            return True
        experiment = state.get("experiment") or {}
        control = state.get("control") or {}
        exp_settled = int(experiment.get("settled") or 0)
        ctl_settled = int(control.get("settled") or 0)
        if exp_settled < _EXPERIMENT_MIN_SETTLED or ctl_settled < _CONTROL_MIN_SETTLED:
            return False
        exp_negative = int(experiment.get("negative") or 0) / exp_settled
        ctl_negative = int(control.get("negative") or 0) / ctl_settled
        if exp_negative - ctl_negative < _NEGATIVE_RATE_DELTA:
            return False
        if ctl_negative > 0 and exp_negative < ctl_negative * _NEGATIVE_RATE_RATIO:
            return False
        state["circuit_disabled"] = True
        state["circuit_reason"] = "negative_rate_delta"
        state["circuit_tripped_at"] = int(time.time())
        state["experiment_negative_rate"] = round(exp_negative, 4)
        state["control_negative_rate"] = round(ctl_negative, 4)
        _save_state(state)
        return True
    return False


def reset_experiment_circuit() -> None:
    """人工恢复：清除熔断状态并开启新的统计窗口。"""
    with interprocess_file_lock(experiment_state_path().with_suffix(".lock")):
        state = _load_state()
        state.pop("circuit_disabled", None)
        state.pop("circuit_reason", None)
        state.pop("circuit_tripped_at", None)
        state.pop("experiment_negative_rate", None)
        state.pop("control_negative_rate", None)
        state.pop("experiment", None)
        state.pop("control", None)
        state.pop("settled_request_ids", None)
        _save_state(state)


def experiment_status() -> dict[str, Any]:
    state = _load_state()
    return {
        "circuit_disabled": bool(state.get("circuit_disabled")),
        "circuit_reason": state.get("circuit_reason"),
        "circuit_tripped_at": state.get("circuit_tripped_at"),
        "experiment": state.get("experiment") or {},
        "control": state.get("control") or {},
        "channel_circuits": state.get("channel_circuits") or {},
    }


def clear_experiment_data_for_tests() -> None:
    for path in (exposures_path(), experiment_state_path()):
        try:
            path.unlink()
        except OSError:
            pass


def _looks_negative(text: str) -> bool:
    return bool(_NEGATIVE_PHRASE_RE.search(str(text or "")))


async def settle_pending_semantic_exposures(*, now: int | None = None) -> int:
    """结算观察窗口已过的 exposure：目标用户续接 + 保守负反馈，并累计实验计数。"""
    from pallas.core.foundation.db import make_message_repository

    current = int(time.time()) if now is None else int(now)
    rows = _load_unsettled_exposures()
    if not rows:
        return 0
    repo = make_message_repository()
    settled = 0
    settled_ids: set[str] = set()
    for item in rows[:_OUTCOME_MAX_PER_PASS]:
        delivered_at = int(item.get("delivered_at") or 0)
        if delivered_at <= 0 or current - delivered_at < _OUTCOME_WINDOW_SEC:
            continue
        bot_id = int(item.get("bot_id") or 0)
        group_id = int(item.get("group_id") or 0)
        target_user = int(item.get("user_id") or 0)
        if bot_id <= 0 or group_id <= 0:
            continue
        try:
            followups = await repo.list_group_messages_after(
                group_id,
                after_time=delivered_at,
                after_message_id=int(item.get("bot_message_id") or 0) or None,
                limit=24,
            )
        except Exception as exc:
            log_rate_limited(logger, "warning", "semantic_experiment.query", "语义 exposure 结算查询失败：{}", exc)
            continue
        target_followup = False
        negative = False
        seen_messages: set[object] = set()
        human_followups = 0
        from pallas.product.llm.sender_identity import is_peer_bot

        for message in followups:
            user_id = int(getattr(message, "user_id", 0) or 0)
            if user_id <= 0 or user_id == bot_id or is_peer_bot(user_id):
                continue
            text = str(getattr(message, "plain_text", "") or getattr(message, "raw_message", "") or "")
            message_id = int(getattr(message, "message_id", 0) or 0)
            message_key: object = message_id or (
                int(getattr(message, "time", 0) or 0),
                user_id,
                text,
            )
            if message_key in seen_messages:
                continue
            seen_messages.add(message_key)
            human_followups += 1
            if user_id == target_user:
                target_followup = True
                if _looks_negative(text):
                    negative = True
            if human_followups >= _OUTCOME_MAX_FOLLOWUPS:
                break
        request_id = str(item.get("request_id") or "")
        record_experiment_outcome(
            request_id=request_id,
            bucket=int(item.get("bucket") if item.get("bucket") is not None else 1),
            target_followup=target_followup,
            negative=negative,
        )
        settled_ids.add(request_id)
        settled += 1
    if settled_ids:
        mark_exposures_settled(settled_ids)
    maybe_trip_circuit()
    return settled


async def _settle_loop() -> None:
    while True:
        await asyncio.sleep(_OUTCOME_SETTLE_INTERVAL_SEC)
        try:
            await settle_pending_semantic_exposures()
        except Exception as exc:
            log_rate_limited(logger, "warning", "semantic_experiment.loop", "语义 exposure 自动结算失败：{}", exc)


_startup_bound = False
_settle_task: asyncio.Task[Any] | None = None


def register_semantic_experiment_loop() -> None:
    global _startup_bound, _settle_task
    if _startup_bound:
        return
    _startup_bound = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        global _settle_task
        _settle_task = asyncio.create_task(_settle_loop(), name="semantic_style_experiment_settle")

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        global _settle_task
        if _settle_task is not None:
            _settle_task.cancel()
            await asyncio.gather(_settle_task, return_exceptions=True)
            _settle_task = None
