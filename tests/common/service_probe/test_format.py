from src.common.service_probe import ServiceProbeResult, format_probe_line, format_probe_lines, format_probe_text


def test_format_probe_line() -> None:
    ok = ServiceProbeResult("测试", "节点", True, 88, 200, None)
    assert format_probe_line(ok) == "测试 节点：88ms"
    noted = ServiceProbeResult("测试", "节点", True, 5, 200, "附带说明")
    assert format_probe_line(noted) == "测试 节点：5ms（附带说明）"
    err = ServiceProbeResult("测试", "节点", False, None, None, "超时")
    assert format_probe_line(err) == "测试 节点：超时"


def test_format_probe_line_omit_repeated_category() -> None:
    r = ServiceProbeResult("牛牛画画", "备线1", True, 10, 200, None)
    assert format_probe_line(r, show_category=False, indent=5) == "     备线1：10ms"


def test_format_probe_lines_groups_same_category() -> None:
    results = [
        ServiceProbeResult("牛牛画画", "主网关", True, 88, 200, None),
        ServiceProbeResult("牛牛画画", "备线1", False, None, None, "超时"),
        ServiceProbeResult("MAA远控", "获取任务", True, 5, 200, None),
        ServiceProbeResult("MAA远控", "汇报任务", True, 4, 200, None),
    ]
    assert format_probe_lines(results) == [
        "牛牛画画 主网关：88ms",
        "     备线1：超时",
        "MAA远控 获取任务：5ms",
        "      汇报任务：4ms",
    ]


def test_format_probe_text_joins_lines() -> None:
    results = [ServiceProbeResult("唱歌", "服务", False, None, None, "未启用 sing_enable")]
    assert format_probe_text(results) == "唱歌 服务：未启用 sing_enable"
