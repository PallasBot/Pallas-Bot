from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest


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
        assert "[启动] 就绪" in texts
        assert "[启动] 版本：v4.0.0" in texts
        assert "[启动] 角色：Hub" in texts
        assert "[启动] 监听：127.0.0.1:8088" in texts
        assert "[启动] 数据库：SQLite" in texts
        assert "[启动] 插件：本地 1 · 内置 10 · pip 0 · 扩展 1" in texts
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
        assert "[启动] 角色：Worker" in info_texts
        assert "[启动] 分片：#3" in info_texts
        assert "[启动] 监听：0.0.0.0:8090" in info_texts
        assert "[启动] 控制台：http://127.0.0.1:8090/pallas/" in info_texts

        mock_warning.assert_called_once()
        assert mock_warning.call_args.args[1] == "[启动] 降级 · LLM：unreachable err=refused"


def test_format_helpers_cover_common_facts() -> None:
    import pallas.core.foundation.startup_report as startup_report

    assert startup_report._format_llm("ok v=4.0.0 provider=chain switches=POLISH") == (
        "正常，版本 4.0.0，通道 chain，开关 POLISH"
    )
    assert (
        startup_report._format_ingress("prefix=74 exact=68 modules=13 strict=False")
        == "前缀规则 74 · 精确规则 68 · 模块 13 · 严格模式 关"
    )
    assert startup_report._format_scheduler("ready") == "已就绪"
