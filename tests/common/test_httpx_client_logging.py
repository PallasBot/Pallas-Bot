from __future__ import annotations

import httpx
import pytest

from pallas.core.shared.utils import HTTPXClient


@pytest.mark.asyncio
async def test_httpx_client_get_logs_transport_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []

    class DummyClient:
        is_closed = False

        async def get(self, url: str, **kwargs):  # noqa: ARG002
            raise httpx.ConnectError("connection refused")

    async def fake_ensure_client():
        return DummyClient()

    async def fake_reset_client() -> None:
        return None

    monkeypatch.setattr(HTTPXClient, "_ensure_client", fake_ensure_client)
    monkeypatch.setattr(HTTPXClient, "_reset_client", fake_reset_client)
    monkeypatch.setattr("pallas.core.shared.utils.logger.error", lambda msg: messages.append(msg))
    monkeypatch.setattr("pallas.core.shared.utils.logger.warning", lambda msg: messages.append(msg))

    result = await HTTPXClient.get("http://127.0.0.1:9099/api/play/pallas")

    assert result is None
    assert messages
    assert "ConnectError" in messages[0]
    assert "connection refused" in messages[0]
    assert any("Request GET http://127.0.0.1:9099/api/play/pallas failed after retries" in msg for msg in messages)
