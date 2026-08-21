from __future__ import annotations

from unittest.mock import patch


def test_register_and_reapply_file_sink(monkeypatch):
    """文件 sink 登记后，reapply 按磁盘 LOG_LEVEL 以新级别重建。"""
    from nonebot.log import logger

    from pallas.core.foundation.logging import reapply_runtime_log_level, register_repo_file_sink
    from pallas.core.foundation.config import repo_settings as rs

    def fake_add(sink, *, level, **kwargs):
        fake_add.calls.append(level)
        return 99

    fake_add.calls = []
    fake_remove = lambda _id: None  # noqa: E731

    monkeypatch.setattr(rs, "repo_env_raw_value", lambda name: "DEBUG" if name == "LOG_LEVEL" else None)
    with patch.object(logger, "add", side_effect=fake_add), patch.object(logger, "remove", side_effect=fake_remove):
        register_repo_file_sink(logger, "{time} {message}", path="/tmp/x.log")
        assert fake_add.calls == ["DEBUG"]

        monkeypatch.setattr(rs, "repo_env_raw_value", lambda name: "WARNING" if name == "LOG_LEVEL" else None)
        reapply_runtime_log_level()
        assert fake_add.calls == ["DEBUG", "WARNING"]
