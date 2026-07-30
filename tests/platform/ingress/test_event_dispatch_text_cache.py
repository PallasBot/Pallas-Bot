from __future__ import annotations

from unittest.mock import MagicMock

from pallas.core.platform.ingress import matcher_activation as activation


def test_event_dispatch_texts_cached_per_event() -> None:
    activation.clear_event_dispatch_text_cache()
    event = MagicMock()
    event.raw_message = "hello"
    event.get_plaintext.return_value = "hello"
    first = activation.event_dispatch_texts(event)
    second = activation.event_dispatch_texts(event)
    assert first == second == ("hello", "hello")
    assert event.get_plaintext.call_count == 1
    activation.clear_event_dispatch_text_cache()
    activation.event_dispatch_texts(event)
    assert event.get_plaintext.call_count == 2
