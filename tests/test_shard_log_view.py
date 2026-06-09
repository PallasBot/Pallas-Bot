from src.platform.shard.logs.view import dedupe_log_lines_preserve_order, merge_cluster_log_lines
from src.console.web.bot_web import fill_missing_log_entry_times, parse_nonebot_log_line


def test_dedupe_log_lines():
    lines = [
        "[worker-0] RuntimeError: x",
        "[worker-0] RuntimeError: x",
        "[worker-0] other",
    ]
    out = dedupe_log_lines_preserve_order(lines)
    assert len(out) == 2


def test_parse_shard_prefixed_line():
    e = parse_nonebot_log_line(
        "[worker-6] 05-21 22:44:15 | INFO     | __main__:43 - bot_worker: shard_id=6 port=7976",
    )
    assert "worker-6" in e["scope"]
    assert "7976" in e["message"]


def test_parse_raw_line_no_fake_now_time():
    e = parse_nonebot_log_line("[worker-6] RuntimeError: Module src.plugins.sing is not loaded")
    assert e["time"] == ""
    assert e["scope"] == "worker-6"


def test_merge_dedupes_identical():
    hub = ["05-21 12:00:00 | INFO | src:1 - hub ok"]
    merged = merge_cluster_log_lines(10, "all", hub_ring_lines=hub)
    assert len(merged) <= 10


def test_merge_dedupes_same_body_across_shard_tags(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "hub.log").write_text(
        "05-21 12:00:00 | INFO | src:1 - message_scrub 启动配置 · ok\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    hub_ring = ["05-21 12:00:00 | INFO | src:1 - message_scrub 启动配置 · ok"]
    merged = merge_cluster_log_lines(10, "all", hub_ring_lines=hub_ring)
    scrub = [ln for ln in merged if "message_scrub 启动配置" in ln]
    assert len(scrub) == 1


def test_parse_nonebot_bracket_line():
    e = parse_nonebot_log_line(
        "[worker-2] 05-22 00:38:12 [SUCCESS] nonebot | Succeeded to load plugin",
    )
    assert e["time"]
    assert "worker-2" in e["scope"]
    assert e["level"] == "success"


def test_parse_double_shard_prefix_bracket_line():
    e = parse_nonebot_log_line(
        "[worker-6.bootstrap] [worker-6.bootstrap] 05-22 01:03:47 [INFO] nonebot | hello",
    )
    assert e["level"] == "info"
    assert "worker-6.bootstrap" in e["scope"]
    assert e["message"] == "hello"


def test_merge_traceback_stays_near_error_not_latest_time(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "05-22 02:02:19 | ERROR    | src:32 - [uvicorn] Traceback\n"
        "  File \"a.py\", line 1\n"
        "RuntimeError: Cannot add middleware after an application has started\n"
        "05-22 02:12:13 | INFO     | src:32 - Application startup complete.\n"
        "05-22 02:13:20 | DEBUG    | nonebot:178 - Running PreProcessors...\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    entries = fill_missing_log_entry_times([parse_nonebot_log_line(ln) for ln in merged])
    err = [e for e in entries if "Cannot add middleware" in str(e.get("message") or "")]
    assert err
    assert "02:02:19" in err[0]["time"]


def test_fill_time_on_exception_continuation():
    rows = [
        parse_nonebot_log_line(
            "[worker-6] 2026-05-22 00:38:07,740 - ERROR - gc cleanup",
        ),
        parse_nonebot_log_line("[worker-6] asyncio.exceptions.CancelledError: Cancelled via cancel scope"),
    ]
    out = fill_missing_log_entry_times(rows)
    assert out[1]["time"] == out[0]["time"]


def test_merge_log_line_continuations_tree_dump():
    from src.console.web.bot_web import merge_log_line_continuations

    lines = [
        "[worker-99] 05-24 20:49:06 | INFO     | nonebot:178 - Event will be handled",
        "[worker-99] |  L <class 'collections.abc.Awaitable'>",
        "[worker-99] |  L {'bot': Bot(type='OneBot V11')}",
        "[worker-99] 05-24 20:49:07 | DEBUG    | nonebot:178 - next",
    ]
    merged = merge_log_line_continuations(lines)
    assert len(merged) == 2
    assert "Awaitable" in merged[0]
    assert "Bot(type=" in merged[0]
    assert merged[1].endswith("next")


def test_merge_log_entry_continuations():
    from src.console.web.bot_web import merge_log_entry_continuations

    rows = fill_missing_log_entry_times(
        [
            parse_nonebot_log_line(
                "[worker-99] 05-24 20:49:06 | INFO     | nonebot:178 - payload",
            ),
            parse_nonebot_log_line("[worker-99] |  L {'k': 1}"),
            parse_nonebot_log_line("[worker-99] |  L {'k': 2}"),
        ],
    )
    merged = merge_log_entry_continuations(rows)
    assert len(merged) == 1
    assert "|  L {'k': 1}" in merged[0]["message"]
    assert "|  L {'k': 2}" in merged[0]["message"]
