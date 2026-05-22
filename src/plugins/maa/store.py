from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from ulid import ULID

from src.common.config import UserConfig

from .tasks import MaaTaskSpec, build_task_payload, normalize_device_id


@dataclass(slots=True)
class NotifyTarget:
    bot_id: int
    user_id: int
    group_id: int | None = None


@dataclass(slots=True)
class PendingTask:
    task_id: str
    user: str
    device: str
    task_type: str
    params: str | None
    notify: NotifyTarget
    created_at: float = field(default_factory=time.time)
    reported: bool = False


def pending_task_to_dict(task: PendingTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "user": task.user,
        "device": task.device,
        "task_type": task.task_type,
        "params": task.params,
        "notify": {
            "bot_id": int(task.notify.bot_id),
            "user_id": int(task.notify.user_id),
            "group_id": task.notify.group_id,
        },
        "created_at": float(task.created_at),
        "reported": bool(task.reported),
    }


def pending_task_from_dict(data: dict[str, Any]) -> PendingTask | None:
    if not isinstance(data, dict):
        return None
    raw_notify = data.get("notify")
    if not isinstance(raw_notify, dict):
        return None
    try:
        notify = NotifyTarget(
            bot_id=int(raw_notify["bot_id"]),
            user_id=int(raw_notify["user_id"]),
            group_id=raw_notify.get("group_id"),
        )
    except (KeyError, TypeError, ValueError):
        return None
    try:
        return PendingTask(
            task_id=str(data["task_id"]),
            user=str(data["user"]),
            device=str(data["device"]),
            task_type=str(data["task_type"]),
            params=data.get("params"),
            notify=notify,
            created_at=float(data.get("created_at") or time.time()),
            reported=bool(data.get("reported")),
        )
    except (KeyError, TypeError, ValueError):
        return None


@dataclass(slots=True)
class DeviceRecord:
    device: str
    verified: bool = False
    last_seen: float = field(default_factory=time.time)
    alias: str = ""


def match_device_ref(ref: str, devices: dict[str, DeviceRecord]) -> tuple[str | None, str | None]:
    """按完整 id、别名或 id 前缀（至少 8 位 hex）匹配已绑定设备。"""
    text = (ref or "").strip()
    if not text:
        return None, "请提供设备标识符、别名或 id 前缀。"
    verified = {k: v for k, v in devices.items() if v.verified}
    if not verified:
        return None, "尚未绑定 MAA 设备。"

    norm = normalize_device_id(text)
    if norm and norm in verified:
        return norm, None

    by_alias = [d.device for d in verified.values() if d.alias and d.alias == text]
    if len(by_alias) == 1:
        return by_alias[0], None
    if len(by_alias) > 1:
        return None, "别名重复，请改用设备标识符。"

    prefix = text.lower()
    if len(prefix) < 8 or not all(c in "0123456789abcdef" for c in prefix):
        return None, "未找到该设备；可发「牛牛MAA状态」查看列表，或用完整 32 位标识符。"
    by_prefix = [did for did in verified if did.startswith(prefix)]
    if len(by_prefix) == 1:
        return by_prefix[0], None
    if len(by_prefix) > 1:
        return None, "前缀匹配到多台设备，请写更长的标识符或使用别名。"
    return None, "未找到该设备；可发「牛牛MAA状态」查看已绑定列表。"


class MaaStore:
    """MAA 设备登记、任务队列（内存）；已绑定设备列表持久化到 UserConfig。

    队列仅按 user+device 过滤后交给 getTask，不替 MAA 做唤醒或子项前置。见 docs/plugins/maa/README.md「维护者说明」。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seen: dict[tuple[str, str], float] = {}
        self._pending: dict[str, PendingTask] = {}
        self._active_device: dict[str, str] = {}

    async def touch_seen(self, user: str, device: str, ttl: int) -> None:
        norm = normalize_device_id(device)
        if not norm:
            return
        key = (user.strip(), norm)
        if not key[0] or not key[1]:
            return
        now = time.time()
        async with self._lock:
            self._seen[key] = now
            cutoff = now - ttl
            self._seen = {k: ts for k, ts in self._seen.items() if ts >= cutoff}
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_seen_registry import touch_maa_seen_sync

            await asyncio.to_thread(touch_maa_seen_sync, user, norm)

    async def was_seen(self, user: str, device: str, ttl: int) -> bool:
        norm = normalize_device_id(device)
        if not norm:
            return False
        key = (user.strip(), norm)
        now = time.time()
        async with self._lock:
            ts = self._seen.get(key)
            if ts is not None and now - ts <= ttl:
                return True
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_seen_registry import was_maa_seen_sync

            return await asyncio.to_thread(was_maa_seen_sync, user, norm, ttl)
        return False

    def validate_new_alias(self, devices: dict[str, DeviceRecord], device: str, alias: str) -> str | None:
        name = (alias or "").strip()
        if not name:
            return None
        if len(name) > 32:
            return "别名最长 32 个字符。"
        for d in devices.values():
            if d.device != device and d.alias and d.alias == name:
                return f"别名「{name}」已被其他设备使用。"
        return None

    async def bind_device(
        self,
        qq_id: int,
        user: str,
        device: str,
        ttl: int,
        *,
        alias: str = "",
    ) -> str | None:
        user_key = str(qq_id)
        norm_device = normalize_device_id(device)
        if not norm_device:
            return "设备标识符格式不正确。"
        if user.strip() != user_key:
            return "MAA 用户标识符须填写你的 QQ 号，与当前账号不一致。"
        if not await self.was_seen(user, norm_device, ttl):
            return "未检测到该设备向牛牛轮询，请先在 MAA 中配置远控端点并保存后再试。"
        cfg = UserConfig(qq_id)
        devices = await self._load_devices(cfg)
        name = (alias or "").strip()
        if not name:
            prev = devices.get(norm_device)
            name = prev.alias if prev else ""
        alias_err = self.validate_new_alias(devices, norm_device, name)
        if alias_err:
            return alias_err
        devices[norm_device] = DeviceRecord(
            device=norm_device,
            verified=True,
            last_seen=time.time(),
            alias=name,
        )
        await self._save_devices(cfg, devices)
        await self._set_active_device(qq_id, norm_device)
        return None

    async def list_devices(self, qq_id: int) -> list[DeviceRecord]:
        cfg = UserConfig(qq_id)
        return list((await self._load_devices(cfg)).values())

    async def get_active_device(self, qq_id: int) -> str | None:
        user_key = str(qq_id)
        async with self._lock:
            active = self._active_device.get(user_key)
        if active:
            return active
        cfg = UserConfig(qq_id)
        persisted = await self._load_active_device(cfg)
        if persisted:
            async with self._lock:
                self._active_device[user_key] = persisted
            return persisted
        devices = await self.list_devices(qq_id)
        verified = [d for d in devices if d.verified]
        if len(verified) == 1:
            await self._set_active_device(qq_id, verified[0].device)
            return verified[0].device
        return None

    async def resolve_bound_device(self, qq_id: int, ref: str) -> tuple[str | None, str | None]:
        devices = await self._load_devices(UserConfig(qq_id))
        return match_device_ref(ref, devices)

    async def set_active_device(self, qq_id: int, ref: str) -> str | None:
        device, err = await self.resolve_bound_device(qq_id, ref)
        if err:
            return err
        if device is None:
            return "未找到该设备。"
        await self._set_active_device(qq_id, device)
        return None

    async def set_device_alias(self, qq_id: int, ref: str, alias: str) -> str | None:
        device, err = await self.resolve_bound_device(qq_id, ref)
        if err:
            return err
        if device is None:
            return "未找到该设备。"
        name = (alias or "").strip()
        cfg = UserConfig(qq_id)
        devices = await self._load_devices(cfg)
        alias_err = self.validate_new_alias(devices, device, name)
        if alias_err:
            return alias_err
        rec = devices.get(device)
        if rec is None or not rec.verified:
            return "未找到已绑定的该设备。"
        devices[device] = DeviceRecord(
            device=rec.device,
            verified=rec.verified,
            last_seen=rec.last_seen,
            alias=name,
        )
        await self._save_devices(cfg, devices)
        return None

    def format_device_line(self, record: DeviceRecord, *, active: bool) -> str:
        mark = "（当前）" if active else ""
        if record.alias:
            short = record.device if len(record.device) <= 12 else f"{record.device[:8]}…"
            return f"- {record.alias} [{short}]{mark}"
        return f"- {record.device}{mark}"

    async def _set_active_device(self, qq_id: int, device: str) -> None:
        norm = normalize_device_id(device) or device
        user_key = str(qq_id)
        async with self._lock:
            self._active_device[user_key] = norm
        await UserConfig(qq_id)._update("maa_active_device", norm)

    async def get_stage_plan(self, qq_id: int) -> list[str]:
        cfg = UserConfig(qq_id)
        raw = await cfg._find("maa_stage_plan")
        if not isinstance(raw, list):
            return []
        return [item.strip() for item in raw[:4] if isinstance(item, str)]

    async def set_stage_plan(self, qq_id: int, stages: list[str]) -> None:
        cfg = UserConfig(qq_id)
        await cfg._update("maa_stage_plan", stages[:4])

    async def _load_active_device(self, cfg: UserConfig) -> str | None:
        raw = await cfg._find("maa_active_device")
        if not isinstance(raw, str) or not raw.strip():
            return None
        return normalize_device_id(raw.strip()) or raw.strip()

    async def _save_devices(self, cfg: UserConfig, devices: dict[str, DeviceRecord]) -> None:
        payload = {
            k: {
                "verified": v.verified,
                "last_seen": v.last_seen,
                "alias": v.alias or "",
            }
            for k, v in devices.items()
        }
        await cfg._update("maa_devices", payload)

    async def enqueue(
        self,
        qq_id: int,
        specs: list[MaaTaskSpec],
        notify: NotifyTarget,
        *,
        attach_screenshot: bool,
    ) -> tuple[list[str], str | None]:
        user_key = str(qq_id)
        device = await self.get_active_device(qq_id)
        if not device:
            devices = await self.list_devices(qq_id)
            verified = [d for d in devices if d.verified]
            if len(verified) > 1:
                return [], (
                    "已绑定多台 MAA 设备，请先「牛牛切换MAA设备 <标识符或别名>」指定当前设备，"
                    "或发「牛牛MAA状态」查看列表。"
                )
            return [], "尚未绑定 MAA 设备，请私聊发送「牛牛绑定MAA <设备标识符>」。"
        devices = await self.list_devices(qq_id)
        if not any(d.device == device and d.verified for d in devices):
            return [], "当前设备未绑定或已失效，请重新绑定。"

        from src.common.shard.coord.maa_route_registry import register_maa_user_route

        register_maa_user_route(user_key)
        from src.common.shard.registry.config import is_sharding_active

        shard_pending = is_sharding_active()
        task_ids: list[str] = []
        to_enqueue: list[PendingTask] = []
        async with self._lock:
            for spec in specs:
                task_id = str(ULID())
                rec = PendingTask(
                    task_id=task_id,
                    user=user_key,
                    device=device,
                    task_type=spec.task_type,
                    params=spec.params,
                    notify=notify,
                )
                if not shard_pending:
                    self._pending[task_id] = rec
                to_enqueue.append(rec)
                task_ids.append(task_id)
            if attach_screenshot and specs and specs[-1].task_type not in {"CaptureImage", "CaptureImageNow"}:
                shot_id = str(ULID())
                rec = PendingTask(
                    task_id=shot_id,
                    user=user_key,
                    device=device,
                    task_type="CaptureImage",
                    params=None,
                    notify=notify,
                )
                if not shard_pending:
                    self._pending[shot_id] = rec
                to_enqueue.append(rec)
                task_ids.append(shot_id)
        if shard_pending:
            from src.common.shard.coord.maa_pending_registry import enqueue_task_sync

            for rec in to_enqueue:
                await asyncio.to_thread(enqueue_task_sync, pending_task_to_dict(rec))
        return task_ids, None

    async def pending_tasks_for(self, user: str, device: str) -> list[dict[str, Any]]:
        norm = normalize_device_id(device)
        if not norm:
            return []
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_pending_registry import list_pending_sync

            raw = await asyncio.to_thread(list_pending_sync, user.strip(), norm)
            items = [pending_task_from_dict(x) for x in raw]
            items = [t for t in items if t is not None]
        else:
            key_user, key_device = user.strip(), norm
            async with self._lock:
                items = [
                    t
                    for t in self._pending.values()
                    if t.user == key_user and t.device == key_device and not t.reported
                ]
        return [
            build_task_payload(t.task_id, MaaTaskSpec(t.task_type, t.params))
            for t in sorted(items, key=lambda x: x.created_at)
        ]

    async def mark_reported(self, task_id: str) -> PendingTask | None:
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_pending_registry import mark_reported_sync

            raw = await asyncio.to_thread(mark_reported_sync, task_id)
            return pending_task_from_dict(raw) if raw else None
        async with self._lock:
            task = self._pending.get(task_id)
            if not task:
                return None
            task.reported = True
            return task

    async def pending_count_for_user(self, qq_id: int) -> int:
        user_key = str(qq_id)
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_pending_registry import pending_count_for_user_sync

            return await asyncio.to_thread(pending_count_for_user_sync, user_key)
        async with self._lock:
            return sum(1 for t in self._pending.values() if t.user == user_key and not t.reported)

    async def pending_count_for_device(self, qq_id: int, device: str) -> int:
        norm = normalize_device_id(device)
        if not norm:
            return 0
        user_key = str(qq_id)
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_pending_registry import pending_count_for_device_sync

            return await asyncio.to_thread(pending_count_for_device_sync, user_key, norm)
        async with self._lock:
            return sum(1 for t in self._pending.values() if t.user == user_key and t.device == norm and not t.reported)

    async def clear_pending(self, qq_id: int, *, device: str | None = None) -> int:
        """移除未汇报任务；device 为 None 时清空该 QQ 全部待拉取任务。"""
        user_key = str(qq_id)
        norm = normalize_device_id(device) if device else None
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_pending_registry import clear_pending_sync

            return await asyncio.to_thread(clear_pending_sync, user_key, device=norm)
        async with self._lock:
            remove_ids = [
                tid
                for tid, t in self._pending.items()
                if t.user == user_key and not t.reported and (norm is None or t.device == norm)
            ]
            for tid in remove_ids:
                del self._pending[tid]
        return len(remove_ids)

    async def pending_type_counts(self, qq_id: int, *, device: str | None = None) -> dict[str, int]:
        user_key = str(qq_id)
        norm = normalize_device_id(device) if device else None
        from src.common.shard.registry.config import is_sharding_active

        if is_sharding_active():
            from src.common.shard.coord.maa_pending_registry import pending_type_counts_sync

            return await asyncio.to_thread(pending_type_counts_sync, user_key, device=norm)
        counts: dict[str, int] = {}
        async with self._lock:
            for t in self._pending.values():
                if t.user != user_key or t.reported:
                    continue
                if norm is not None and t.device != norm:
                    continue
                counts[t.task_type] = counts.get(t.task_type, 0) + 1
        return counts

    async def is_device_verified(self, user: str, device: str) -> bool:
        try:
            qq_id = int(user.strip())
        except ValueError:
            return False
        devices = await self.list_devices(qq_id)
        norm = normalize_device_id(device)
        if not norm:
            return False
        return any(d.device == norm and d.verified for d in devices)

    async def _load_devices(self, cfg: UserConfig) -> dict[str, DeviceRecord]:
        raw: Any = await cfg._find("maa_devices")
        if not isinstance(raw, dict):
            return {}
        out: dict[str, DeviceRecord] = {}
        for device_id, meta in raw.items():
            if not isinstance(device_id, str) or not isinstance(meta, dict):
                continue
            canon = normalize_device_id(device_id)
            if not canon:
                continue
            alias_raw = meta.get("alias")
            alias = alias_raw.strip() if isinstance(alias_raw, str) else ""
            out[canon] = DeviceRecord(
                device=canon,
                verified=bool(meta.get("verified")),
                last_seen=float(meta.get("last_seen") or 0),
                alias=alias,
            )
        return out


maa_store = MaaStore()
