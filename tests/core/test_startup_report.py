from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest


def test_emit_startup_banner_outputs_ascii_logo(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    import pallas.core.foundation.startup_report as startup_report

    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    startup_report.emit_startup_banner()
    out = buf.getvalue()
    assert "██" in out
    assert out.strip().startswith("█")
    assert "-" not in startup_report._BANNER


def test_render_banner_is_plain_text() -> None:
    import pallas.core.foundation.startup_report as startup_report

    rendered = startup_report._render_banner()
    assert rendered == startup_report._BANNER
    assert "\x1b[" not in rendered


def test_emit_startup_summary_logs_runtime_and_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    import pallas.core.foundation.startup_report as startup_report

    startup_report.reset_startup_report_for_tests()
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setattr(
        startup_report,
        "get_driver",
        lambda: SimpleNamespace(config=SimpleNamespace(host="127.0.0.1", port=8088)),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.bot_version.get_pallas_bot_version_for_reporting",
        lambda: "v4.0.0",
    )
    monkeypatch.setattr("pallas.core.platform.bot_runtime.roles.bot_role", lambda: "hub")
    monkeypatch.setattr("pallas.core.platform.bot_runtime.roles.is_sharded_worker", lambda: False)

    startup_report.register_startup_fact("plugins", "local=1 src=10 pip=0 extra=1")
    startup_report.register_startup_fact("llm", "ok v=4.0.0 switches=LLM_CHAT")
    startup_report.emit_startup_summary()

    with patch.object(startup_report.logger, "info") as mock_info:
        startup_report.emit_startup_summary()
        mock_info.assert_not_called()

    snapshot = startup_report.startup_report_snapshot()
    assert snapshot["emitted"] is True
    assert snapshot["facts"]["plugins"] == "local=1 src=10 pip=0 extra=1"

    startup_report.reset_startup_report_for_tests()
    with patch.object(startup_report.logger, "info") as mock_info:
        startup_report.register_startup_fact("plugins", "local=1 src=10 pip=0 extra=1")
        startup_report.emit_startup_summary()
        texts = [call.args[1] for call in mock_info.call_args_list]
        assert "[初始化] Pallas-Bot 已就绪" in texts
        assert "[初始化] 版本：v4.0.0" in texts
        assert "[初始化] 角色：Hub" in texts
        assert "[初始化] 监听：127.0.0.1:8088" in texts
        assert "[初始化] 数据库：SQLite" in texts
        assert "[初始化] 已成功载入 12 个插件：本地 1，内置 10，额外目录 1" in texts
        assert all("\n" not in t for t in texts)


def test_emit_startup_summary_logs_warning_block(monkeypatch: pytest.MonkeyPatch) -> None:
    import pallas.core.foundation.startup_report as startup_report

    startup_report.reset_startup_report_for_tests()
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setattr(
        startup_report,
        "get_driver",
        lambda: SimpleNamespace(config=SimpleNamespace(host=None, port=8090)),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.bot_version.get_pallas_bot_version_for_reporting",
        lambda: "v4.0.1",
    )
    monkeypatch.setattr("pallas.core.platform.bot_runtime.roles.bot_role", lambda: "worker")
    monkeypatch.setattr("pallas.core.platform.bot_runtime.roles.is_sharded_worker", lambda: True)
    monkeypatch.setenv("PALLAS_SHARD_ID", "3")

    with (
        patch.object(startup_report.logger, "info") as mock_info,
        patch.object(
            startup_report.logger,
            "warning",
        ) as mock_warning,
    ):
        startup_report.register_startup_fact("console", "http://127.0.0.1:8090/pallas/")
        startup_report.register_startup_warning("llm", "unreachable err=refused")
        startup_report.emit_startup_summary()

        info_texts = [call.args[1] for call in mock_info.call_args_list]
        assert "[初始化] 角色：Worker" in info_texts
        assert "[初始化] 分片：#3" in info_texts
        assert "[初始化] 监听：0.0.0.0:8090" in info_texts
        assert "[控制台] 已就绪：http://127.0.0.1:8090/pallas/" in info_texts

        mock_warning.assert_called_once()
        assert mock_warning.call_args.args[1] == "[LLM] 已降级：unreachable err=refused"


def test_startup_summary_lists_component_ready_scheduled_and_skipped_states() -> None:
    import pallas.core.foundation.startup_report as startup_report

    startup_report.reset_startup_report_for_tests()
    startup_report.register_startup_ready("入站调度", "scheduler=8 send_workers=4")
    startup_report.register_startup_scheduled("语料预取", "workers=2")
    startup_report.register_startup_skipped("语义风格回填", "reason=disabled")
    startup_report.register_startup_degraded("消息过滤", "reason=lexicon_unreadable")

    info_lines, warning_lines = startup_report.build_startup_summary_lines(base_lines=[])

    assert "[入站调度] 已就绪：scheduler=8 send_workers=4" in info_lines
    assert "[语料预取] 已调度：workers=2" in info_lines
    assert "[语义风格回填] 已跳过：reason=disabled" in info_lines
    assert all("（" not in line and "）" not in line for line in info_lines)
    assert all("\n" not in line and not line.startswith("[初始化]  ") for line in info_lines)
    assert warning_lines == ["[消息过滤] 已降级：reason=lexicon_unreadable"]


def test_startup_summary_aggregates_plugin_ready_events() -> None:
    import pallas.core.foundation.startup_report as startup_report

    startup_report.reset_startup_report_for_tests()
    startup_report.register_plugin_startup_ready("arcana", ["arcana.draw"])

    info_lines, warning_lines = startup_report.build_startup_summary_lines(base_lines=[])

    assert "[Ready] Plugin [arcana] registered commands [Draw]" in info_lines
    assert warning_lines == []


def test_startup_summary_lists_failed_and_slow_plugins() -> None:
    import pallas.core.foundation.startup_report as startup_report

    startup_report.reset_startup_report_for_tests()
    info_lines, warning_lines = startup_report.build_startup_summary_lines(
        base_lines=[],
        facts={
            "plugins": "local=8 src=12 official=12 nonebot=0 extra=0 skip=2 skip_sources=src:1,official:1",
            "plugin_failures": "weather,bilibili",
            "plugin_slow": "ai_media=1.42,protocol=1.08",
        },
    )

    assert "[初始化] 已成功载入 32 个插件：本地 8，内置 12，官方 12；配置跳过 2：内置 1，官方 1" in info_lines
    assert "[插件] 载入失败：weather、bilibili" in info_lines
    assert "[插件] 载入较慢：ai_media 1.42 秒、protocol 1.08 秒" in info_lines
    assert warning_lines == []


def test_format_helpers_cover_common_facts() -> None:
    import pallas.core.foundation.startup_report as startup_report

    assert startup_report._format_llm("ok v=4.0.0 provider=chain model=moonshot chat=enabled") == (
        "已就绪：版本 4.0.0，Provider chain，模型 moonshot，智能对话已启用"
    )
    assert startup_report._format_plugins(
        "local=8 src=12 official=12 nonebot=3 pypi=3 community=4 extra=2 skip=2 skip_sources=src:1,nonebot:1"
    ) == (
        "已成功载入 41 个插件：本地 8，内置 12，官方 12，NoneBot 3，社区 4，额外目录 2；配置跳过 2：内置 1，NoneBot 1"
    )
    assert startup_report._format_plugins("local=1 modules=12/14 official=3 pypi=2 extra=0") == (
        "已成功载入 16 个插件：本地 1，内置 12/14，官方 3"
    )
    assert (
        startup_report._format_ingress("prefix=74 exact=68 modules=13 strict=False")
        == "已载入 74 条前缀规则、68 条精确规则，覆盖 13 个模块；严格路由未启用"
    )
    assert startup_report._format_scheduler("ready") == "已就绪"
