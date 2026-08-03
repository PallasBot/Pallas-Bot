from pallas.product.llm.tools.background_store import (
    complete_background_tool_task,
    create_background_tool_task,
    drain_background_tool_events,
    list_recoverable_background_tool_tasks,
    mark_background_tool_task_running,
)
from pallas.product.llm.tools.context import ToolInvokeContext


def test_background_tool_store_preserves_recovery_state_and_scoped_completion(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    context = ToolInvokeContext(bot_id=1, group_id=2, user_id=3, approved_tools=frozenset({"web.search"}))
    task = create_background_tool_task(
        tool_name="web.search",
        arguments={"query": "公告"},
        context=context,
        max_execution_ms=4_000,
    )

    assert list_recoverable_background_tool_tasks() == [task]
    assert mark_background_tool_task_running(task["task_id"])["status"] == "running"
    assert (
        complete_background_tool_task(task["task_id"], {"ok": True, "result": {"summary": "done"}})["status"]
        == "completed"
    )
    assert drain_background_tool_events(ToolInvokeContext(bot_id=1, group_id=2, user_id=4)) == []
    assert drain_background_tool_events(context) == [
        {
            "task_id": task["task_id"],
            "tool": "web.search",
            "status": "completed",
            "result": {"summary": "done"},
            "error": "",
        }
    ]
    assert drain_background_tool_events(context) == []
