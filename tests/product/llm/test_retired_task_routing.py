from __future__ import annotations

from pallas.product.llm.task_routing import task_route_tier


def test_retired_repeater_tasks_have_no_routing_tier() -> None:
    for task in ("repeater_select", "repeater_polish", "repeater_polish_lite", "repeater_fallback"):
        assert task_route_tier(task) == ""
