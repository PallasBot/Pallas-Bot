"""Backend-neutral orchestration for database lifecycle management."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from contextlib import suppress
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

from .lifecycle_adapters import LifecycleAdapter, make_lifecycle_adapter
from .lifecycle_models import (
    LifecycleCatalog,
    LifecycleDatasetCatalogItem,
    LifecycleJob,
    LifecycleObjectStat,
    LifecyclePolicy,
    LifecyclePreview,
)
from .lifecycle_policy_store import load_lifecycle_policies, validate_lifecycle_policy
from .lifecycle_registry import DATASETS

_GLOBAL_LOCK_KEY = "pallas:db_lifecycle:lock"
_GLOBAL_LOCK_TTL_SEC = 6 * 60 * 60
_GLOBAL_LOCK_REFRESH_SEC = _GLOBAL_LOCK_TTL_SEC // 3


class LifecycleConflictError(RuntimeError):
    pass


class LifecycleService:
    def __init__(
        self,
        *,
        adapter: LifecycleAdapter | None = None,
        policy_loader: Callable[[], dict[str, LifecyclePolicy]] = load_lifecycle_policies,
        token_ttl_sec: int = 900,
    ) -> None:
        self.adapter = adapter or make_lifecycle_adapter()
        self.policy_loader = policy_loader
        self.token_ttl_sec = token_ttl_sec
        self.token_secret = secrets.token_bytes(32)
        self.preview_nonces: dict[str, float] = {}
        self.jobs: dict[str, LifecycleJob] = {}
        self.job_tasks: dict[str, asyncio.Task[None]] = {}

    async def catalog(self) -> LifecycleCatalog:
        objects = await self.adapter.discover_objects()
        policies = self.policy_loader()
        by_dataset: dict[str, list[LifecycleObjectStat]] = {}
        unmanaged: list[LifecycleObjectStat] = []
        for item in objects:
            if item.dataset_id is None:
                unmanaged.append(item)
            else:
                by_dataset.setdefault(item.dataset_id, []).append(item)

        datasets: list[LifecycleDatasetCatalogItem] = []
        for dataset_id, definition in DATASETS.items():
            present = by_dataset.get(dataset_id, [])
            datasets.append(
                LifecycleDatasetCatalogItem(
                    dataset_id=dataset_id,
                    label=definition.label,
                    risk=definition.risk,
                    registered_objects=definition.objects,
                    present_objects=tuple(item.name for item in present),
                    row_count=sum_known(item.row_count for item in present),
                    size_bytes=sum_known(item.size_bytes for item in present),
                    policy=policies.get(dataset_id, definition.default_policy),
                    supports_retention=definition.supports_retention,
                    supports_max_bytes=definition.supports_max_bytes,
                    errors=tuple(item.error for item in present if item.error),
                )
            )
        return LifecycleCatalog(
            backend=self.adapter.backend,
            datasets=tuple(datasets),
            unmanaged_objects=tuple(unmanaged),
        )

    async def preview(self, dataset_id: str, policy: LifecyclePolicy) -> LifecyclePreview:
        validate_dataset(dataset_id)
        validate_lifecycle_policy(dataset_id, policy)
        candidate_rows, candidate_bytes = await self.adapter.preview_dataset(dataset_id, policy)  # type: ignore[attr-defined]
        expires_at = time.time() + self.token_ttl_sec
        nonce = secrets.token_urlsafe(12)
        self.prune_preview_nonces()
        self.preview_nonces[nonce] = expires_at
        payload = {
            "backend": self.adapter.backend,
            "dataset_id": dataset_id,
            "policy": asdict(policy),
            "candidate_rows": candidate_rows,
            "candidate_bytes": candidate_bytes,
            "expires_at": expires_at,
            "nonce": nonce,
        }
        return LifecyclePreview(
            dataset_id=dataset_id,
            candidate_rows=candidate_rows,
            candidate_bytes=candidate_bytes,
            confirmation_token=self.sign_payload(payload),
            expires_at=expires_at,
        )

    async def run_enabled_policies(self, *, exclude: frozenset[str] = frozenset()) -> list[LifecycleJob]:
        jobs: list[LifecycleJob] = []
        for dataset_id, policy in self.policy_loader().items():
            if dataset_id in exclude:
                continue
            job = await self.run_dataset_policy(dataset_id, policy)
            if job is not None:
                jobs.append(job)
        return jobs

    async def run_dataset_policy(self, dataset_id: str, policy: LifecyclePolicy | None = None) -> LifecycleJob | None:
        resolved = policy or self.policy_loader().get(dataset_id)
        if resolved is None or not resolved.enabled:
            return None
        preview = await self.preview(dataset_id, resolved)
        if preview.candidate_rows <= 0:
            return None
        job = self.start_job(dataset_id, resolved, preview.confirmation_token)
        await self.wait_for_job(job.job_id)
        return job

    def start_job(self, dataset_id: str, policy: LifecyclePolicy, confirmation_token: str) -> LifecycleJob:
        validate_dataset(dataset_id)
        payload = self.verify_token(confirmation_token)
        expected = {
            "backend": self.adapter.backend,
            "dataset_id": dataset_id,
            "policy": asdict(policy),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise LifecycleConflictError("确认信息不匹配，请重新预估")
        nonce = str(payload.get("nonce") or "")
        if not nonce or nonce not in self.preview_nonces:
            raise LifecycleConflictError("确认信息已使用或无效，请重新预估")
        if self.active_job() is not None:
            raise LifecycleConflictError("已有生命周期任务正在运行")
        self.preview_nonces.pop(nonce, None)
        job = LifecycleJob(
            job_id=secrets.token_urlsafe(12),
            dataset_id=dataset_id,
            created_at=time.time(),
        )
        self.jobs[job.job_id] = job
        self.job_tasks[job.job_id] = asyncio.create_task(self.run_job(job, policy))
        self.prune_job_history()
        return job

    def get_job(self, job_id: str) -> LifecycleJob | None:
        return self.jobs.get(job_id)

    async def wait_for_job(self, job_id: str) -> None:
        task = self.job_tasks.get(job_id)
        if task is not None:
            await task

    def active_job(self) -> LifecycleJob | None:
        return next((job for job in self.jobs.values() if job.status in {"queued", "running"}), None)

    async def run_job(self, job: LifecycleJob, policy: LifecyclePolicy) -> None:
        lock_owner = job.job_id
        heartbeat: asyncio.Task[None] | None = None
        try:
            if not await acquire_global_lock(lock_owner):
                raise LifecycleConflictError("其他分片正在执行生命周期任务")
            heartbeat = asyncio.create_task(refresh_global_lock_until_cancelled(lock_owner))
            job.status = "running"
            job.started_at = time.time()
            deleted_rows, freed_bytes = await self.adapter.prune_dataset(job.dataset_id, policy)  # type: ignore[attr-defined]
            job.deleted_rows = deleted_rows
            job.freed_bytes = freed_bytes
            job.status = "completed"
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job.status = "failed"
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            job.finished_at = time.time()
            await release_global_lock(lock_owner)

    def sign_payload(self, payload: dict[str, object]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.token_secret, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw + signature).decode().rstrip("=")

    def verify_token(self, token: str) -> dict[str, object]:
        try:
            padded = token + "=" * (-len(token) % 4)
            signed = base64.urlsafe_b64decode(padded.encode())
            raw, signature = signed[:-32], signed[-32:]
            expected = hmac.new(self.token_secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            raise LifecycleConflictError("确认信息无效，请重新预估") from None
        if not isinstance(payload, dict) or float(payload.get("expires_at") or 0) < time.time():
            raise LifecycleConflictError("确认信息已过期，请重新预估")
        return payload

    def prune_preview_nonces(self) -> None:
        now = time.time()
        for nonce, expires_at in tuple(self.preview_nonces.items()):
            if expires_at < now:
                self.preview_nonces.pop(nonce, None)

    def prune_job_history(self) -> None:
        if len(self.jobs) <= 24:
            return
        finished = sorted(
            (job for job in self.jobs.values() if job.finished_at is not None),
            key=lambda job: job.finished_at or 0,
        )
        for job in finished[: len(self.jobs) - 24]:
            self.jobs.pop(job.job_id, None)
            self.job_tasks.pop(job.job_id, None)


def sum_known(values: Iterable[int | None]) -> int | None:
    items = list(values)
    if not items:
        return 0
    if any(value is None for value in items):
        return None
    return sum(int(value) for value in items)


def validate_dataset(dataset_id: str) -> None:
    if dataset_id not in DATASETS:
        raise ValueError(f"未知生命周期数据集: {dataset_id}")


async def run_lifecycle_dataset_maintenance(dataset_id: str) -> LifecycleJob | None:
    return await LifecycleService().run_dataset_policy(dataset_id)


async def acquire_global_lock(owner: str) -> bool:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client

    client = get_coord_redis_client()
    if client is None:
        return True
    try:
        result = await asyncio.to_thread(
            client.set,
            _GLOBAL_LOCK_KEY,
            owner,
            nx=True,
            ex=_GLOBAL_LOCK_TTL_SEC,
        )
    except Exception:  # noqa: BLE001
        return True
    return bool(result)


async def release_global_lock(owner: str) -> None:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client

    client = get_coord_redis_client()
    if client is None:
        return
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
    try:
        await asyncio.to_thread(client.eval, script, 1, _GLOBAL_LOCK_KEY, owner)
    except Exception:  # noqa: BLE001
        return


async def refresh_global_lock_until_cancelled(owner: str) -> None:
    while True:
        await asyncio.sleep(_GLOBAL_LOCK_REFRESH_SEC)
        if not await refresh_global_lock(owner):
            return


async def refresh_global_lock(owner: str) -> bool:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client

    client = get_coord_redis_client()
    if client is None:
        return False
    script = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
    )
    try:
        result = await asyncio.to_thread(client.eval, script, 1, _GLOBAL_LOCK_KEY, owner, _GLOBAL_LOCK_TTL_SEC)
    except Exception:  # noqa: BLE001
        return False
    return bool(result)
