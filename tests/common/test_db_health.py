"""db_health 状态迁移与门禁。"""

from __future__ import annotations

import pytest
from pallas.core.foundation.db.db_health import (
    get_db_health,
    is_db_unhealthy,
    note_db_pool_pressure,
    note_db_probe_result,
    reset_db_health_for_tests,
    should_skip_noncritical_db,
)

from pallas.core.foundation.db.pallas_console_data import normalize_console_table_name


@pytest.fixture(autouse=True)
def _reset_health():
    reset_db_health_for_tests()
    yield
    reset_db_health_for_tests()


def test_probe_fail_twice_marks_unhealthy():
    note_db_probe_result(False, reason="timeout")
    assert get_db_health().status == "degraded"
    assert not should_skip_noncritical_db()

    note_db_probe_result(False, reason="timeout")
    assert is_db_unhealthy()
    assert should_skip_noncritical_db()
    assert "timeout" in get_db_health().reason


def test_probe_ok_twice_recovers_from_unhealthy():
    note_db_probe_result(False, reason="down")
    note_db_probe_result(False, reason="down")
    assert is_db_unhealthy()

    note_db_probe_result(True)
    assert is_db_unhealthy()  # 需连续两次成功

    note_db_probe_result(True)
    assert get_db_health().status == "healthy"
    assert not should_skip_noncritical_db()


def test_pool_pressure_degrades_without_unhealthy():
    note_db_probe_result(True, pool={"utilization": 0.4, "under_pressure": False})
    note_db_pool_pressure(under_pressure=True, pool={"utilization": 0.9, "under_pressure": True})
    assert get_db_health().status == "degraded"
    assert not is_db_unhealthy()


def test_normalize_console_table_name_whitelist():
    assert normalize_console_table_name("config") == "bot_config"
    assert normalize_console_table_name("blacklist") == "blacklist"
    with pytest.raises(ValueError, match="白名单"):
        normalize_console_table_name("message")
    with pytest.raises(ValueError, match="白名单"):
        normalize_console_table_name("pg_stat_activity")
