from __future__ import annotations

from pallas.product.llm.orchestration.subagent import create_subagent_run, run_subagent_job
from pallas.product.llm.orchestration.task_store import cancel_task, create_task, list_tasks
from pallas.product.llm.tools.contracts import ProactiveDeliveryContract, TaskContract, ToolCapability
from pallas.product.persona.catchphrase_bank import (
    compile_catchphrase_prompt_lines,
    is_auto_promote_eligible,
    list_catchphrases,
    promote_catchphrase,
    propose_catchphrase_from_bot_success,
    reject_catchphrase,
)


def test_tool_capability_and_contracts() -> None:
    assert ToolCapability.EXTERNAL_NETWORK.value == "external_network"
    task = TaskContract(task_id="t1", name="remind", group_id=1)
    assert task.status == "pending"
    delivery = ProactiveDeliveryContract(group_id=1, text="hello")
    assert delivery.source == "task"


def test_task_store_create_and_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    task = create_task("once", {"text": "hi"}, group_id=733291779)
    assert task.task_id.startswith("task-")
    assert any(item.task_id == task.task_id for item in list_tasks())
    cancelled = cancel_task(task.task_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"


def test_subagent_run_records_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    task = create_task("research", {"query": "x"}, group_id=1)
    run = create_subagent_run(task.task_id, allowed_tools=["web.search"], budget=2)
    finished = run_subagent_job(run, steps=["search", "summarize"])
    assert finished.status == "completed"
    assert finished.artifacts
    assert finished.run_id == run.run_id


def test_catchphrase_promotion_requires_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    first = propose_catchphrase_from_bot_success(1001, 11, "那很牛了", "日常接话")
    assert first is not None
    assert not is_auto_promote_eligible(first)
    second = propose_catchphrase_from_bot_success(1001, 22, "那很牛了", "日常接话")
    third = propose_catchphrase_from_bot_success(1001, 33, "那很牛了", "日常接话")
    assert third is not None
    assert is_auto_promote_eligible(third)
    promoted = promote_catchphrase(third.entry_id)
    assert promoted is not None
    assert promoted.status == "active"
    assert any("那很牛了" in line for line in compile_catchphrase_prompt_lines(1001))
    rejected = reject_catchphrase(second.entry_id if second else third.entry_id)
    assert rejected is not None
    assert list_catchphrases(1001)
