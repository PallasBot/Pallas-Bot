"""Repeater test isolation: reset leaked ingress load state between tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_message_load_state():
    from pallas.core.platform.ingress.message_load import reset_message_load_for_tests

    reset_message_load_for_tests()
    yield
    reset_message_load_for_tests()
