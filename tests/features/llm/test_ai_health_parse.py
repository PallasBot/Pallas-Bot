from pallas.product.llm.ai_health_parse import (
    capability_health_circuit,
    image_health_circuit,
    llm_health_configuration_ok,
    llm_health_runtime_detail,
    llm_health_summary,
    parse_media_tasks,
    tts_health_summary,
)


def test_llm_health_runtime_detail() -> None:
    body = {
        "llm": {
            "provider_mode": "remote_first",
            "configuration_ok": True,
            "local_reachable": True,
            "remote_reachable": False,
        },
    }
    detail = llm_health_runtime_detail(body)
    assert detail is not None
    assert "remote_first" in detail
    assert "remote 不可达" in detail


def test_llm_health_configuration_ok() -> None:
    assert llm_health_configuration_ok({"llm": {"configuration_ok": False}}) is False
    assert llm_health_configuration_ok({"status": "ok"}) is None


def test_llm_health_circuit() -> None:
    from pallas.product.llm.ai_health_parse import llm_health_circuit

    body = {
        "llm": {
            "circuit_state": "open",
            "consecutive_failures": 4,
            "recent_failure_class": "timeout",
            "health_state": "unhealthy",
        }
    }
    circuit = llm_health_circuit(body)
    assert circuit is not None
    assert circuit["circuit_state"] == "open"
    assert circuit["consecutive_failures"] == 4


def test_image_health_circuit() -> None:
    body = {
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
    }
    circuit = image_health_circuit(body)
    assert circuit is not None
    assert circuit["circuit_state"] == "open"
    assert circuit["consecutive_failures"] == 2
    assert circuit["recent_failure_class"] == "timeout"


def test_parse_media_tasks() -> None:
    body = {
        "media_tasks": {
            "queue_depth": 3,
            "active_tasks": 1,
            "total_tasks": 4,
            "health_state": "healthy",
            "circuit_state": "closed",
            "capabilities": [
                {"capability": "image.generate", "queue_depth": 2, "active_tasks": 1, "health_state": "healthy"},
                {"capability": "media.sing", "queue_depth": 1, "active_tasks": 0, "health_state": "healthy"},
            ],
        },
    }
    parsed = parse_media_tasks(body)
    assert parsed is not None
    assert parsed["queue_depth"] == 3
    assert parsed["health_state"] == "healthy"
    assert len(parsed["capabilities"]) == 2


def test_llm_health_summary() -> None:
    body = {
        "llm": {
            "health_state": "degraded",
            "circuit_state": "half_open",
            "recent_failure_class": "provider_unavailable",
            "provider_status": [
                {
                    "id": "local",
                    "kind": "local",
                    "enabled": True,
                    "configured": True,
                    "reachable": False,
                    "health_state": "degraded",
                },
            ],
        },
    }
    summary = llm_health_summary(body)
    assert summary is not None
    assert summary["health_state"] == "degraded"
    assert summary["circuit_state"] == "half_open"
    assert len(summary["provider_status"]) == 1


def test_tts_health_summary() -> None:
    body = {"tts": {"capability": "tts.synthesize", "health_state": "healthy", "celery_enabled": True}}
    summary = tts_health_summary(body)
    assert summary is not None
    assert summary["health_state"] == "healthy"


def test_capability_health_circuit_from_media_tasks() -> None:
    body = {
        "media_tasks": {
            "capabilities": [
                {
                    "capability": "media.sing",
                    "circuit_state": "open",
                    "consecutive_failures": 2,
                    "recent_failure_class": "timeout",
                },
            ],
        },
    }
    circuit = capability_health_circuit(body, "media.sing")
    assert circuit is not None
    assert circuit["circuit_state"] == "open"
