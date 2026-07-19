from __future__ import annotations

from pallas.api.ai_runtime_health import (
    image_runtime_circuit_is_open,
    image_runtime_circuit_snapshot,
    sing_health_circuit_from_cache,
)
from pallas.core.shared.ai_health_cache import clear_ai_health_cache, update_ai_health_cache


def test_image_runtime_circuit_reads_ai_health_cache() -> None:
    clear_ai_health_cache()
    assert image_runtime_circuit_is_open() is False
    update_ai_health_cache({
        "image": {
            "health_state": "degraded",
            "backends": [
                {
                    "circuit_state": "open",
                    "consecutive_failures": 2,
                    "recent_failure_class": "timeout",
                },
            ],
        },
    })
    assert image_runtime_circuit_is_open() is True
    snap = image_runtime_circuit_snapshot()
    assert snap.consecutive_failures == 2
    assert snap.recent_failure_reason == "timeout"


def test_sing_health_circuit_from_media_tasks_capabilities() -> None:
    clear_ai_health_cache()
    update_ai_health_cache({
        "media_tasks": {
            "capabilities": [
                {
                    "capability": "media.sing",
                    "circuit_state": "half_open",
                    "consecutive_failures": 1,
                    "health_state": "degraded",
                },
            ],
        },
    })
    circuit = sing_health_circuit_from_cache()
    assert circuit is not None
    assert circuit["circuit_state"] == "half_open"
