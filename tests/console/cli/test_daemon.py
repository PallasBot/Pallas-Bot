from __future__ import annotations

from unittest.mock import Mock

import pytest


def test_daemon_restarts_after_consecutive_health_failures() -> None:
    from pallas.console.cli.daemon import run_daemon

    health = iter([False, False, False])
    lifecycle = Mock(return_value=0)

    sleeps = 0

    def stop_loop(_delay: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 4:
            raise StopIteration

    with pytest.raises(StopIteration):
        run_daemon(
            interval=1,
            timeout=1,
            fail_threshold=3,
            cooldown=1,
            port=8088,
            probe=lambda _port: next(health),
            lifecycle=lifecycle,
            sleep=stop_loop,
        )

    assert lifecycle.call_args_list[0].args == ("start",)
    assert lifecycle.call_args_list[0].kwargs == {"mode": "unified", "extra_args": ["--detach"]}
    assert lifecycle.call_args_list[1].args == ("restart",)
    assert lifecycle.call_args_list[1].kwargs == {
        "mode": "unified",
        "extra_args": ["--detach", "--skip-port-sync"],
    }
    assert lifecycle.call_args_list[-1].args == ("stop",)


def test_daemon_rejects_invalid_timing() -> None:
    from pallas.console.cli.daemon import run_daemon

    with pytest.raises(ValueError, match="interval/timeout"):
        run_daemon(interval=0, probe=lambda _port: True)
