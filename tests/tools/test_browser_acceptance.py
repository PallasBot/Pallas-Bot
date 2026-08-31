import json

import pytest

from tools import browser_acceptance as tool


def test_find_chrome_returns_candidate_or_none():
    result = tool.find_chrome()
    assert result is None or isinstance(result, str)


def test_wait_for_pages_raises_on_timeout(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("no endpoint")

    monkeypatch.setattr(tool.urllib.request, "urlopen", _boom)
    with pytest.raises(RuntimeError):
        tool._wait_for_pages(9999, timeout=0.1)


def test_wait_for_pages_returns_pages(monkeypatch):
    pages = [{"type": "page", "webSocketDebuggerUrl": "ws://x"}]

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(pages).encode()

    monkeypatch.setattr(tool.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert tool._wait_for_pages(9999, timeout=0.1) == pages


@pytest.mark.asyncio
async def test_run_assertions_passed_and_failed(monkeypatch):
    async def fake_evaluate(ws_url, expression, *, timeout_s=10.0):
        value = expression == "true"
        return {"result": {"result": {"value": value}}}

    monkeypatch.setattr(tool, "_evaluate", fake_evaluate)
    results = await tool._run_assertions("ws://x", ["true", "false"])
    assert results[0]["status"] == "passed"
    assert results[1]["status"] == "failed"


@pytest.mark.asyncio
async def test_run_assertions_error(monkeypatch):
    async def fake_evaluate(ws_url, expression, *, timeout_s=10.0):
        return {"error": "boom"}

    monkeypatch.setattr(tool, "_evaluate", fake_evaluate)
    results = await tool._run_assertions("ws://x", ["expr"])
    assert results[0]["status"] == "error"
    assert results[0]["error"] == "boom"


@pytest.mark.asyncio
async def test_accept_no_chrome(monkeypatch):
    monkeypatch.setattr(tool, "find_chrome", lambda: None)
    payload = await tool._accept("http://x", ["true"])
    assert payload["status"] == "error"
    assert "no chromium" in payload["error"]
