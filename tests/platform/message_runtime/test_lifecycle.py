from __future__ import annotations

from pallas.core.platform.message_runtime import lifecycle


def setup_function() -> None:
    lifecycle.reset_direct_runtime_for_tests()


def teardown_function() -> None:
    lifecycle.reset_direct_runtime_for_tests()


def test_direct_runtime_is_available_without_experiment_configuration() -> None:
    lifecycle.configure_direct_runtime()

    assert lifecycle.direct_runtime_for_group(100) is not None
    assert lifecycle.direct_runtime_for_group(999) is not None
