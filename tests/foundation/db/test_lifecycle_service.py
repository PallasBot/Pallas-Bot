import asyncio

import pytest

from pallas.core.foundation.db import lifecycle_service
from pallas.core.foundation.db.lifecycle_models import LifecycleObjectStat, LifecyclePolicy
from pallas.core.foundation.db.lifecycle_service import LifecycleConflictError, LifecycleService


class FakeAdapter:
    backend = "postgresql"

    def __init__(self) -> None:
        self.pruned: list[str] = []

    async def discover_objects(self) -> list[LifecycleObjectStat]:
        return [
            LifecycleObjectStat("context", 10, 1000, "repeater_context", False, None),
            LifecycleObjectStat("context_answer", 20, 2000, "repeater_context", False, None),
            LifecycleObjectStat("plugin_table", 5, 500, None, True, "protected_unknown"),
        ]

    async def preview_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
        return 12, 4096

    async def prune_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
        await asyncio.sleep(0)
        self.pruned.append(dataset_id)
        return 12, 4096


@pytest.mark.asyncio
async def test_catalog_aggregates_present_objects_and_keeps_unknown_visible() -> None:
    service = LifecycleService(
        adapter=FakeAdapter(),
        policy_loader=lambda: {"repeater_context": LifecyclePolicy(True, 45, 4096)},
    )

    catalog = await service.catalog()

    context = next(item for item in catalog.datasets if item.dataset_id == "repeater_context")
    assert context.present_objects == ("context", "context_answer")
    assert context.row_count == 30
    assert context.size_bytes == 3000
    assert context.policy == LifecyclePolicy(True, 45, 4096)
    assert context.supports_retention is True
    assert context.supports_max_bytes is False
    assert catalog.unmanaged_objects[0].name == "plugin_table"
    assert catalog.unmanaged_objects[0].protected is True


@pytest.mark.asyncio
async def test_preview_token_is_required_and_bound_to_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def acquire_lock(_owner: str) -> bool:
        return True

    monkeypatch.setattr(lifecycle_service, "acquire_global_lock", acquire_lock)
    service = LifecycleService(adapter=FakeAdapter())
    policy = LifecyclePolicy(True, 30, None)

    preview = await service.preview("message_history", policy)

    assert preview.candidate_rows == 12
    assert preview.candidate_bytes == 4096
    with pytest.raises(LifecycleConflictError, match="确认信息不匹配"):
        service.start_job("message_history", LifecyclePolicy(True, 31, None), preview.confirmation_token)

    job = service.start_job("message_history", policy, preview.confirmation_token)
    await service.wait_for_job(job.job_id)
    completed = service.get_job(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.deleted_rows == 12


@pytest.mark.asyncio
async def test_preview_rejects_policy_fields_unsupported_by_dataset() -> None:
    service = LifecycleService(adapter=FakeAdapter())

    with pytest.raises(ValueError, match="不支持"):
        await service.preview("llm_memory", LifecyclePolicy(True, 30, None))


@pytest.mark.asyncio
async def test_only_one_lifecycle_job_can_be_active() -> None:
    gate = asyncio.Event()

    class BlockingAdapter(FakeAdapter):
        async def prune_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
            await gate.wait()
            return 1, 1

    service = LifecycleService(adapter=BlockingAdapter())
    policy = LifecyclePolicy(True, 30, None)
    first_preview = await service.preview("message_history", policy)
    service.start_job("message_history", policy, first_preview.confirmation_token)
    second_preview = await service.preview("message_history", policy)

    with pytest.raises(LifecycleConflictError, match="已有生命周期任务"):
        service.start_job("message_history", policy, second_preview.confirmation_token)
    gate.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_scheduled_maintenance_only_runs_enabled_policies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def acquire_lock(_owner: str) -> bool:
        return True

    monkeypatch.setattr(lifecycle_service, "acquire_global_lock", acquire_lock)
    adapter = FakeAdapter()
    service = LifecycleService(
        adapter=adapter,
        policy_loader=lambda: {
            "message_history": LifecyclePolicy(False, 30, None),
            "image_cache": LifecyclePolicy(True, 90, 20 * 1024**3),
        },
    )

    jobs = await service.run_enabled_policies()

    assert [job.dataset_id for job in jobs] == ["image_cache"]
    assert adapter.pruned == ["image_cache"]


@pytest.mark.asyncio
async def test_acquire_global_lock_degrades_when_redis_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.coord import redis_claim

    monkeypatch.setattr(redis_claim, "get_coord_redis_client", lambda: None)

    assert await lifecycle_service.acquire_global_lock("owner") is True
