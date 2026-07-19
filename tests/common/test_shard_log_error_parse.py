from __future__ import annotations

from pallas.core.platform.shard.logs.errors import parse_log_error_from_record


class _FakeExc:
    type = KeyError
    value = KeyError("1354970010")
    traceback = None


class _FakeRecord:
    def __init__(self, *, message: str, exception: object | None) -> None:
        self._message = message
        self._exception = exception

    def __getitem__(self, key: str):
        if key == "message":
            return self._message
        if key == "exception":
            return self._exception
        raise KeyError(key)


def test_parse_log_error_from_record_uses_text_traceback_when_longer():
    tb = (
        "Traceback (most recent call last):\n"
        '  File "bot_worker.py", line 99, in <module>\n'
        "    nonebot.run()\n"
        '  File "take_name/__init__.py", line 88, in run_change_name\n'
        "KeyError: '1354970010'\n"
    )
    record = _FakeRecord(message="take_name: change_name 定时任务失败", exception=_FakeExc())
    exc_type, msg, out_tb = parse_log_error_from_record(tb, record)
    assert exc_type == "KeyError"
    assert "take_name" in msg
    assert "bot_worker.py" in out_tb
    assert "KeyError" in out_tb
