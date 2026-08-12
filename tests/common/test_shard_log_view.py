from __future__ import annotations

from pathlib import Path

from pallas.core.platform.shard.logs.view import (
    ShardLogTailer,
    collect_cluster_log_errors,
    list_shard_log_sources,
    merge_cluster_log_lines,
    prefix_log_source,
    tail_log_file,
)
from pallas.core.platform.shard.registry.store import ShardRecord, ShardRegistry, TestShardConfig


def test_prefix_log_source():
    line = "05-21 12:00:00 | INFO     | src:1 - hello"
    out = prefix_log_source(line, "worker-1")
    assert out.startswith("[worker-1] ")
    assert "hello" in out
    assert out == f"[worker-1] {line}"


def test_prefix_log_source_idempotent():
    line = "[worker-1] 05-21 12:00:00 | INFO     | src:1 - hello"
    assert prefix_log_source(line, "worker-1") == line


def test_list_shard_log_sources_skips_orphan_worker_log(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - ok0\n",
        encoding="utf-8",
    )
    (log_dir / "worker-99.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - orphan\n",
        encoding="utf-8",
    )
    reg = ShardRegistry(
        shards=[
            ShardRecord(id=0, port=8090, bot_ids=["111"]),
        ],
        assignments={"111": 0},
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.registry.store.get_shard_registry", lambda: reg)

    sources = list_shard_log_sources()
    assert sources == ["hub", "worker-0"]
    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert any("ok0" in row for row in merged)
    assert not any("orphan" in row for row in merged)


def test_list_shard_log_sources_includes_test_shard_with_bots(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - ok0\n",
        encoding="utf-8",
    )
    (log_dir / "worker-99.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - test ok\n",
        encoding="utf-8",
    )
    reg = ShardRegistry(
        shards=[
            ShardRecord(id=0, port=8090, bot_ids=["111"]),
            ShardRecord(id=99, port=8199, role="test", bot_ids=["222"]),
        ],
        assignments={"111": 0, "222": 99},
        test=TestShardConfig(enabled=True, shard_id=99, port=8199),
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.registry.store.get_shard_registry", lambda: reg)

    sources = list_shard_log_sources()
    assert sources == ["hub", "worker-0", "worker-99"]
    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert any("test ok" in row for row in merged)


def test_list_shard_log_sources_skips_test_shard_without_bots(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-99.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - idle test\n",
        encoding="utf-8",
    )
    reg = ShardRegistry(
        shards=[ShardRecord(id=99, port=8199, role="test", bot_ids=[])],
        test=TestShardConfig(enabled=True, shard_id=99, port=8199),
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.registry.store.get_shard_registry", lambda: reg)

    assert list_shard_log_sources() == ["hub"]
    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert not any("idle test" in row for row in merged)


def test_merge_cluster_sorts_and_limits(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "05-21 10:00:00 | INFO     | a:1 - early worker\n05-21 12:00:00 | INFO     | a:1 - late worker\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)

    hub = [
        "05-21 11:00:00 | INFO     | hub:1 - mid hub",
    ]
    merged = merge_cluster_log_lines(10, "all", hub_ring_lines=hub)
    assert len(merged) == 3
    assert any("[hub]" in row for row in merged)
    assert merged[-1].endswith("late worker") or "late worker" in merged[-1]


def test_merge_cluster_iso_banner_sorts_with_mmdd(tmp_path, monkeypatch):
    """会话横幅为 YYYY-MM-DD，不得因字典序飘到无年份 loguru 行之后。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "hub.log").write_text(
        "2026-07-28 12:03:45 | INFO     | shard_session:0 - === hub START ===\n"
        "07-28 12:03:47 | INFO     | pallas:1 - hub ready\n"
        "07-28 12:08:47 | INFO     | packages:1 - jieba ready\n",
        encoding="utf-8",
    )
    (log_dir / "worker-0.log").write_text(
        "2026-07-28 12:03:47 | INFO     | shard_session:0 - === worker-0 START ===\n"
        "07-28 12:15:00 | SUCCESS  | pallas:1 - late message\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.worker_log_stem_allowed", lambda _stem: True)

    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert any("hub START" in row for row in merged)
    assert any("jieba ready" in row for row in merged)
    assert "late message" in merged[-1]
    start_idx = next(i for i, row in enumerate(merged) if "hub START" in row)
    late_idx = next(i for i, row in enumerate(merged) if "late message" in row)
    assert start_idx < late_idx


def test_merge_cluster_drops_leading_orphan_continuations(tmp_path, monkeypatch):
    """文件尾截在 pretty-print 中间时，无父行续行不应垫在合并结果最底部。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "07-28 12:15:00 | SUCCESS  | pallas:1 - late message\n",
        encoding="utf-8",
    )
    (log_dir / "worker-98.log").write_text(
        '                 └ <function require at 0x7f95926844a0>\n  File "/tmp/x.py", line 1, in <module>\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.worker_log_stem_allowed", lambda _stem: True)

    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert any("late message" in row for row in merged)
    assert not any("require at 0x" in row for row in merged)
    assert merged[-1].endswith("late message") or "late message" in merged[-1]


def test_tail_log_file():
    p = Path(__file__)
    lines = tail_log_file(p, 5)
    assert len(lines) >= 1


def test_worker_glob_excludes_bootstrap(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-1.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - main\n",
        encoding="utf-8",
    )
    (log_dir / "worker-1.bootstrap.log").write_text(
        "asyncio.exceptions.CancelledError: x\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert any("main" in row for row in merged)
    assert not any("CancelledError" in row for row in merged)


def test_collect_cluster_log_errors_no_log_rescan_after_cleanup(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    err_dir = log_dir / "errors"
    err_dir.mkdir(parents=True)
    (log_dir / "hub.log").write_text(
        "05-23 04:25:47 | ERROR    | nonebot:1 - stale hub error\nModuleNotFoundError: nope\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.errors.shard_errors_dir", lambda: err_dir)
    from pallas.core.platform.shard.logs.errors import cleanup_shard_error_archives_sync

    cleanup_shard_error_archives_sync()
    rows = collect_cluster_log_errors(per_file=50, limit=10)
    assert rows == []


def test_collect_cluster_log_errors(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-2.log").write_text(
        "2026-05-21 10:00:01,0 - ERROR - boom worker\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "ValueError: bad\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.errors.shard_logs_dir", lambda: log_dir)
    rows = collect_cluster_log_errors(per_file=50, limit=10)
    assert len(rows) >= 1
    assert any("worker-2" in str(r.get("plugin")) for r in rows)
    assert any(r.get("exc_type") == "ValueError" for r in rows)


def test_exc_type_from_traceback_ignores_stack_frames(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-99.log").write_text(
        '05-23 04:25:47 | ERROR    | nonebot:1 - Failed to import "nonebot_plugin_apscheduler"\n'
        "Traceback (most recent call last):\n"
        '  File "plugin_loader.py", line 176, in load_plugins_for_role\n'
        "    manager.load_plugin(module_path)\n"
        '  File "load.py", line 43, in load_plugin\n'
        "    importlib.import_module(name)\n"
        "ModuleNotFoundError: No module named 'nonebot_plugin_apscheduler'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.errors.shard_logs_dir", lambda: log_dir)
    rows = collect_cluster_log_errors(per_file=80, limit=10)
    assert len(rows) >= 1
    row = next(r for r in rows if "worker-99" in str(r.get("plugin")))
    assert row.get("exc_type") == "ModuleNotFoundError"
    assert "nonebot_plugin_apscheduler" in str(row.get("message") or "")


def test_exc_type_from_loguru_style_traceback(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "Traceback (most recent call last):\n"
        '  File "load.py", line 43, in load_plugin\n'
        "    return manager.load_plugin(module_path)\n"
        "           │       │           └ 'nonebot_plugin_apscheduler'\n"
        "ModuleNotFoundError: No module named 'nonebot_plugin_apscheduler'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.errors.shard_logs_dir", lambda: log_dir)
    rows = collect_cluster_log_errors(per_file=50, limit=10)
    assert rows
    assert rows[-1].get("exc_type") == "ModuleNotFoundError"


def test_shard_log_tailer_skips_hub_file(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "hub.log").write_text(
        "07-28 12:00:00 | INFO     | hub:1 - hub only\n",
        encoding="utf-8",
    )
    (log_dir / "worker-0.log").write_text(
        "07-28 12:00:01 | INFO     | a:1 - worker line\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.worker_log_stem_allowed", lambda _stem: True)

    tailer = ShardLogTailer(source="all")
    # bootstrap 已在 EOF；追加后再 poll
    with (log_dir / "hub.log").open("a", encoding="utf-8") as fh:
        fh.write("07-28 12:00:02 | INFO     | hub:1 - hub new\n")
    with (log_dir / "worker-0.log").open("a", encoding="utf-8") as fh:
        fh.write("07-28 12:00:03 | INFO     | a:1 - worker new\n")
    lines = tailer.poll_new_lines(scope="all")
    assert any("worker new" in ln for ln in lines)
    assert not any("hub new" in ln or "hub-file" in ln for ln in lines)


def test_shard_log_tailer_buffers_partial_line(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    worker = log_dir / "worker-0.log"
    worker.write_text("", encoding="utf-8")
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.worker_log_stem_allowed", lambda _stem: True)

    tailer = ShardLogTailer(source="all")
    with worker.open("ab") as fh:
        fh.write(b"07-28 12:00:00 | INFO     | a:1 - hell")
    assert tailer.poll_new_lines(scope="all") == []
    with worker.open("ab") as fh:
        fh.write(b"o world\n")
    lines = tailer.poll_new_lines(scope="all")
    assert len(lines) == 1
    assert "hello world" in lines[0]
