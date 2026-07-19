from typing import get_type_hints

from pallas.core.shared.ai_runtime_capability import IMAGE_GENERATE
from pallas.core.shared.ai_runtime_failure import (
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    CIRCUIT_UNKNOWN,
    FAILURE_CONNECTION_FAILED,
    FAILURE_RUNTIME_DEGRADED,
    FAILURE_RUNTIME_DISABLED,
    FAILURE_TIMEOUT,
    HEALTH_DEGRADED,
    HEALTH_HEALTHY,
    HEALTH_UNKNOWN,
    RUNTIME_DEGRADED,
    RUNTIME_DISABLED,
    RUNTIME_HEALTHY,
    AiCircuitState,
    AiFailureClass,
    AiHealthState,
    AiRuntimeState,
    failure_class_from_error,
)
from pallas.core.shared.service_probe import (
    ServiceProbeResult,
    build_runtime_probe_result,
    enrich_probe_result_capability,
    format_probe_line,
    format_probe_lines,
    format_probe_text,
    normalize_runtime_probe_result,
    patch_probe_result,
    runtime_result_from_circuit_state,
)


def test_format_probe_line() -> None:
    ok = ServiceProbeResult("测试", "节点", True, 88, 200, None)
    assert format_probe_line(ok) == "【测试】\n· 节点：88ms"
    noted = ServiceProbeResult("测试", "节点", True, 5, 200, "附带说明")
    assert format_probe_line(noted) == "【测试】\n· 节点：5ms（附带说明）"
    err = ServiceProbeResult("测试", "节点", False, None, None, "超时")
    assert format_probe_line(err) == "【测试】\n· 节点：超时"


def test_format_probe_line_site_only() -> None:
    r = ServiceProbeResult("牛牛画画", "备线1", True, 10, 200, None)
    assert format_probe_line(r, show_category=False) == "· 备线1：10ms"


def test_format_probe_lines_groups_same_category() -> None:
    results = [
        ServiceProbeResult("牛牛画画", "主网关", True, 88, 200, None),
        ServiceProbeResult("牛牛画画", "备线1", False, None, None, "超时"),
        ServiceProbeResult("MAA远控", "获取任务", True, 5, 200, None),
        ServiceProbeResult("MAA远控", "汇报任务", True, 4, 200, None),
    ]
    assert format_probe_lines(results) == [
        "【牛牛画画】",
        "· 主网关：88ms",
        "· 备线1：超时",
        "",
        "【MAA远控】",
        "· 获取任务：5ms",
        "· 汇报任务：4ms",
    ]


def test_format_probe_text_joins_lines() -> None:
    results = [ServiceProbeResult("唱歌", "服务", False, None, None, "未启用 sing_enable")]
    assert format_probe_text(results) == "【唱歌】\n· 服务：未启用 sing_enable"


def test_format_probe_text_example_layout() -> None:
    results = [
        ServiceProbeResult("牛牛画画", "主网关", True, 403, 200, None),
        ServiceProbeResult("牛牛画画", "备线1", True, 185, 200, None),
        ServiceProbeResult("牛牛画画", "备线2", True, 1761, 200, None),
        ServiceProbeResult("牛牛画画", "备线3", True, 697, 200, None),
        ServiceProbeResult("MAA远控", "获取任务", True, 110, 200, None),
        ServiceProbeResult("MAA远控", "汇报任务", True, 114, 200, None),
        ServiceProbeResult("唱歌", "健康检查", True, 6, 200, None),
    ]
    text = format_probe_text(results)
    assert text.startswith("【牛牛画画】\n· 主网关：403ms")
    assert "【MAA远控】" in text
    assert text.endswith("· 健康检查：6ms")


def test_format_probe_line_prefers_runtime_detail() -> None:
    runtime = ServiceProbeResult(
        "牛牛画画",
        "AI runtime",
        True,
        None,
        None,
        None,
        runtime_state="healthy",
        runtime_detail="正常（开启回退）",
    )
    assert format_probe_line(runtime) == "【牛牛画画】\n· AI runtime：正常（开启回退）"


def test_service_probe_to_dict_includes_capability_fields() -> None:
    result = ServiceProbeResult(
        "唱歌",
        "健康检查",
        True,
        12,
        200,
        None,
        runtime_state="healthy",
        runtime_detail="正常",
        capability_id="media.sing",
        capability_group="media",
    )
    data = result.to_dict()
    assert data["capability_id"] == "media.sing"
    assert data["capability_group"] == "media"
    assert data["runtime_type"] is None


def test_service_probe_to_dict_includes_runtime_health_fields() -> None:
    result = ServiceProbeResult(
        "测试",
        "节点",
        False,
        None,
        None,
        "超时",
        failure_class="timeout",
        health_state="unhealthy",
        circuit_state="open",
        consecutive_failures=3,
        recent_failure_class="timeout",
        queue_load_hint="high",
    )
    data = result.to_dict()
    assert data["failure_class"] == "timeout"
    assert data["health_state"] == "unhealthy"
    assert data["circuit_state"] == "open"
    assert data["consecutive_failures"] == 3
    assert data["recent_failure_class"] == "timeout"
    assert data["queue_load_hint"] == "high"


def test_failure_class_from_error_shared_mapper() -> None:
    assert failure_class_from_error("超时") == "timeout"
    assert failure_class_from_error("ConnectError") == "connection_failed"
    assert failure_class_from_error("未启用 sing_enable") == "runtime_disabled"
    assert failure_class_from_error("熔断中（连续失败 3 次）") == "runtime_degraded"


def test_ai_runtime_failure_exports_shared_constants() -> None:
    assert FAILURE_TIMEOUT == "timeout"
    assert FAILURE_RUNTIME_DISABLED == "runtime_disabled"
    assert HEALTH_HEALTHY == "healthy"
    assert CIRCUIT_CLOSED == "closed"
    assert RUNTIME_DISABLED == "disabled"


def test_service_probe_result_uses_shared_runtime_aliases() -> None:
    annotations = get_type_hints(
        ServiceProbeResult,
        globalns={
            "AiRuntimeState": AiRuntimeState,
            "AiFailureClass": AiFailureClass,
            "AiHealthState": AiHealthState,
            "AiCircuitState": AiCircuitState,
        },
    )
    assert annotations["runtime_state"] == AiRuntimeState | None
    assert annotations["failure_class"] == AiFailureClass | None
    assert annotations["health_state"] == AiHealthState | None
    assert annotations["circuit_state"] == AiCircuitState | None
    assert annotations["recent_failure_class"] == AiFailureClass | None


def test_normalize_runtime_probe_result_defaults_healthy() -> None:
    result = normalize_runtime_probe_result(
        ServiceProbeResult("唱歌", "健康检查", True, 12, 200, None),
    )
    assert result.runtime_state == RUNTIME_HEALTHY
    assert result.health_state == HEALTH_HEALTHY
    assert result.runtime_detail is None
    assert result.failure_class is None


def test_normalize_runtime_probe_result_defaults_degraded_and_detail() -> None:
    result = normalize_runtime_probe_result(
        ServiceProbeResult("唱歌", "健康检查", False, None, None, "连接失败"),
    )
    assert result.runtime_state == RUNTIME_DEGRADED
    assert result.health_state == HEALTH_DEGRADED
    assert result.runtime_detail == "连接失败"
    assert result.failure_class == FAILURE_CONNECTION_FAILED


def test_normalize_runtime_probe_result_supports_disabled_predicate() -> None:
    result = normalize_runtime_probe_result(
        ServiceProbeResult("唱歌", "服务", False, None, None, "未启用 sing_enable"),
        disabled_when=lambda item: "未启用" in str(item.error or ""),
        disabled_health_state=HEALTH_UNKNOWN,
    )
    assert result.runtime_state == RUNTIME_DISABLED
    assert result.health_state == HEALTH_UNKNOWN
    assert result.failure_class == FAILURE_RUNTIME_DISABLED


def test_runtime_result_from_circuit_state_disabled() -> None:
    result = runtime_result_from_circuit_state(
        category="牛牛画画",
        site="AI runtime",
        capability_id="image.generate",
        capability_group="media",
        runtime_type="image",
        disabled_message="未启用（当前为插件直连，开启回退）",
    )
    assert result.runtime_state == RUNTIME_DISABLED
    assert result.runtime_detail == "未启用（当前为插件直连，开启回退）"
    assert result.failure_class == FAILURE_RUNTIME_DISABLED
    assert result.health_state == HEALTH_UNKNOWN
    assert result.circuit_state == CIRCUIT_UNKNOWN
    assert result.consecutive_failures == 0


def test_runtime_result_from_circuit_state_open() -> None:
    result = runtime_result_from_circuit_state(
        category="牛牛画画",
        site="AI runtime",
        capability_id="image.generate",
        capability_group="media",
        runtime_type="image",
        degraded_message="熔断中（连续失败 3 次，不回退）",
        circuit_state=CIRCUIT_OPEN,
        consecutive_failures=3,
        recent_failure_reason="超时",
    )
    assert result.runtime_state == RUNTIME_DEGRADED
    assert result.failure_class == FAILURE_RUNTIME_DEGRADED
    assert result.health_state == HEALTH_DEGRADED
    assert result.circuit_state == CIRCUIT_OPEN
    assert result.recent_failure_class == FAILURE_TIMEOUT


def test_runtime_result_from_circuit_state_half_open() -> None:
    result = runtime_result_from_circuit_state(
        category="牛牛画画",
        site="AI runtime",
        capability_id="image.generate",
        capability_group="media",
        runtime_type="image",
        degraded_message="降级观察中（连续失败 2 次，开启回退）",
        circuit_state=CIRCUIT_HALF_OPEN,
        consecutive_failures=2,
        recent_failure_reason="连接失败",
    )
    assert result.runtime_state == RUNTIME_DEGRADED
    assert result.failure_class == FAILURE_RUNTIME_DEGRADED
    assert result.health_state == HEALTH_DEGRADED
    assert result.circuit_state == CIRCUIT_HALF_OPEN
    assert result.recent_failure_class == FAILURE_CONNECTION_FAILED


def test_runtime_result_from_circuit_state_healthy() -> None:
    result = runtime_result_from_circuit_state(
        category="牛牛画画",
        site="AI runtime",
        capability_id="image.generate",
        capability_group="media",
        runtime_type="image",
        healthy_message="正常（开启回退）",
        circuit_state=CIRCUIT_CLOSED,
        consecutive_failures=0,
    )
    assert result.runtime_state == RUNTIME_HEALTHY
    assert result.runtime_detail == "正常（开启回退）"
    assert result.health_state == HEALTH_HEALTHY
    assert result.circuit_state == CIRCUIT_CLOSED


def test_enrich_probe_result_capability_fills_missing_fields() -> None:
    result = enrich_probe_result_capability(
        ServiceProbeResult("牛牛画画", "AI runtime", True, None, None, None),
        IMAGE_GENERATE,
    )
    assert result.capability_id == "image.generate"
    assert result.capability_group == "media"
    assert result.runtime_type == "image"


def test_enrich_probe_result_capability_preserves_existing_fields() -> None:
    result = enrich_probe_result_capability(
        ServiceProbeResult(
            "测试",
            "节点",
            True,
            1,
            200,
            None,
            capability_id="media.sing",
            capability_group="media",
            runtime_type="media",
        ),
        IMAGE_GENERATE,
    )
    assert result.capability_id == "media.sing"
    assert result.capability_group == "media"
    assert result.runtime_type == "media"


def test_patch_probe_result_overrides_selected_fields_only() -> None:
    result = patch_probe_result(
        ServiceProbeResult(
            "MAA远控",
            "获取任务",
            True,
            8,
            200,
            None,
            runtime_state="healthy",
            capability_id="automation.maa",
            capability_group="automation",
            runtime_type="automation",
            health_state="healthy",
            circuit_state="closed",
            consecutive_failures=1,
            queue_load_hint="low",
        ),
        error="hub 入口已响应",
        runtime_detail="hub 入口已响应",
    )
    assert result.error == "hub 入口已响应"
    assert result.runtime_detail == "hub 入口已响应"
    assert result.capability_id == "automation.maa"
    assert result.health_state == "healthy"
    assert result.circuit_state == "closed"
    assert result.consecutive_failures == 1
    assert result.queue_load_hint == "low"


def test_build_runtime_probe_result_enriches_and_normalizes() -> None:
    result = build_runtime_probe_result(
        IMAGE_GENERATE,
        category="牛牛画画",
        site="网关",
        ok=False,
        latency_ms=None,
        status_code=None,
        error="连接失败",
    )
    assert result.capability_id == "image.generate"
    assert result.capability_group == "media"
    assert result.runtime_type == "image"
    assert result.runtime_state == RUNTIME_DEGRADED
    assert result.health_state == HEALTH_DEGRADED
    assert result.failure_class == FAILURE_CONNECTION_FAILED


def test_build_runtime_probe_result_supports_disabled_health_override() -> None:
    result = build_runtime_probe_result(
        IMAGE_GENERATE,
        category="牛牛画画",
        site="AI runtime",
        ok=False,
        latency_ms=None,
        status_code=None,
        error="未启用",
        runtime_state=RUNTIME_DISABLED,
        failure_class=FAILURE_RUNTIME_DISABLED,
        disabled_health_state=HEALTH_UNKNOWN,
    )
    assert result.runtime_state == RUNTIME_DISABLED
    assert result.health_state == HEALTH_UNKNOWN
