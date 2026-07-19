from pallas.core.shared.service_probe import ServiceProbeResult
from pallas.product.service_gateways.commands import format_connectivity_probe_text


def test_connectivity_text_keeps_latency_for_users() -> None:
    text = format_connectivity_probe_text([
        ServiceProbeResult("智能对话", "主站", True, 123, 200, None),
        ServiceProbeResult("唱歌", "健康检查", False, None, None, "连接失败"),
    ])
    assert "· 主站：123ms" in text
    assert "· 健康检查：连接失败" in text


def test_connectivity_text_omits_draw_ai_runtime_when_plugin_direct() -> None:
    text = format_connectivity_probe_text([
        ServiceProbeResult("牛牛画画", "主网关", True, 88, 200, None),
    ])
    assert "· 主网关：88ms" in text
    assert "AI runtime" not in text
    assert "插件直连" not in text


def test_connectivity_text_hides_runtime_detail_for_users() -> None:
    text = format_connectivity_probe_text([
        ServiceProbeResult(
            "牛牛画画",
            "AI runtime",
            True,
            None,
            None,
            None,
            runtime_state="healthy",
            runtime_detail="正常（开启回退）",
        )
    ])
    assert "正常（开启回退）" not in text
    assert "· AI runtime：可用" in text
