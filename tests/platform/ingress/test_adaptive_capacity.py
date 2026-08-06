from __future__ import annotations

from pallas.core.platform.ingress.adaptive_capacity import adaptive_chat_lane_target, adaptive_scheduler_target


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


def test_adaptive_chat_lane_grows_only_when_the_lane_is_saturated() -> None:
    assert (
        adaptive_chat_lane_target(
            current=6,
            baseline=6,
            maximum=12,
            scheduler={"pending": 40},
            chat_lane={"in_use": 6, "limit": 6},
            pool={"utilization": 0.1},
            send_queue={"depth_live": 0, "max_depth": 256},
        )
        == 7
    )
    assert (
        adaptive_chat_lane_target(
            current=6,
            baseline=6,
            maximum=12,
            scheduler={"pending": 40},
            chat_lane={"in_use": 3, "limit": 6},
            pool={"utilization": 0.1},
            send_queue={"depth_live": 0, "max_depth": 256},
        )
        == 6
    )


def test_adaptive_chat_lane_returns_to_baseline_when_downstream_is_busy() -> None:
    assert (
        adaptive_chat_lane_target(
            current=10,
            baseline=6,
            maximum=12,
            scheduler={"pending": 40},
            chat_lane={"in_use": 10, "limit": 10},
            pool={"utilization": 0.6},
            send_queue={"depth_live": 0, "max_depth": 256},
        )
        == 6
    )
