from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ingress_dispatch_status.py"
_SPEC = importlib.util.spec_from_file_location("ingress_dispatch_status", _SCRIPT)
assert _SPEC is not None
assert _SPEC.loader is not None
_STATUS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_STATUS)


class _Response:
    body = b'{"ok":true,"data":{"group_messages":17,"conversation_scheduler":{"enabled":true}}}'

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


def test_fetch_live_dispatch_metrics_reads_console_api() -> None:
    requested: list[str] = []

    def opener(url: str, *, timeout: float):
        requested.append(url)
        assert timeout == 3.0
        return _Response()

    metrics = _STATUS.fetch_live_dispatch_metrics(port=7969, opener=opener)

    assert metrics["group_messages"] == 17
    assert metrics["conversation_scheduler"]["enabled"] is True
    assert requested == ["http://127.0.0.1:7969/pallas/api/ingress-dispatch"]


def test_fetch_live_dispatch_metrics_rejects_non_object_response() -> None:
    response = _Response()
    response.body = b"[]"

    with pytest.raises(ValueError, match="有效 ingress 指标"):
        _STATUS.fetch_live_dispatch_metrics(port=7969, opener=lambda *_args, **_kwargs: response)
