from __future__ import annotations

from pallas.core.platform.ingress.adaptive_capacity import adaptive_scheduler_target


def test_adaptive_scheduler_uses_idle_pg_and_send_capacity() -> None:
    assert (
        adaptive_scheduler_target(
            current=8,
            baseline=8,
            maximum=12,
            scheduler={"pending": 40, "active": 8},
            pool={"utilization": 0.1},
            send_queue={"depth_live": 0, "max_depth": 256},
        )
        == 9
    )


def test_adaptive_scheduler_returns_to_baseline_when_queue_drains() -> None:
    assert (
        adaptive_scheduler_target(
            current=12,
            baseline=8,
            maximum=12,
            scheduler={"pending": 0, "active": 0},
            pool={"utilization": 0.1},
            send_queue={"depth_live": 0, "max_depth": 256},
        )
        == 8
    )
