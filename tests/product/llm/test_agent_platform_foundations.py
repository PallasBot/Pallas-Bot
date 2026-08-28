from __future__ import annotations

from pallas.product.llm.orchestration.subagent import create_subagent_run, run_subagent_job
from pallas.product.llm.orchestration.task_store import cancel_task, create_task, list_tasks
from pallas.product.llm.tools.contracts import ProactiveDeliveryContract, TaskContract, ToolCapability


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
