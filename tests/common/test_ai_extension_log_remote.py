"""AI 扩展日志 HTTP 回退。"""

from __future__ import annotations

import pytest

from pallas.console.web.ai_extension_log_read import read_ai_extension_logs_payload
from pallas.console.web.ai_extension_log_remote import fetch_remote_ai_extension_logs, parse_remote_log_payload


@pytest.mark.asyncio
async def test_fetch_remote_ai_extension_logs_parses_payload() -> None:
    async def fake_http_json(**kwargs: object) -> dict[str, object]:
        assert kwargs["method"] == "GET"
        assert "ops/logs" in str(kwargs["path"])
        return {
            "ok": True,
            "url": "http://127.0.0.1:9099/api/ops/logs?kind=uvicorn&n=10",
            "data": {
                "kind": "uvicorn",
                "path": "/server/logs/uvicorn.log",
                "lines": ["a", "b"],
                "error": None,
            },
        }

    out = await fetch_remote_ai_extension_logs(
        {"base_url": "http://127.0.0.1:9099"},
        "uvicorn",
        10,
        http_json=fake_http_json,
    )
    assert out is not None
    assert out["source"] == "remote"
    assert out["lines"] == ["a", "b"]


def test_parse_remote_log_payload_error_without_lines() -> None:
    parsed = parse_remote_log_payload({"error": "日志文件不存在", "lines": []}, kind="uvicorn")
    assert parsed["error"] == "日志文件不存在"
    assert parsed["lines"] == []


@pytest.mark.asyncio
async def test_read_ai_extension_logs_payload_prefers_local(tmp_path) -> None:
    log_file = tmp_path / "uvicorn.log"
    log_file.write_text("line-1\nline-2\n", encoding="utf-8")

    async def fail_http_json(**kwargs: object) -> dict[str, object]:
        raise AssertionError("remote should not be called")

    cfg = {"uvicorn_log_file": str(log_file)}
    out = await read_ai_extension_logs_payload(
        cfg,
        "uvicorn",
        10,
        http_json=fail_http_json,
        is_allowed_log_path=lambda path_s: True,
    )
    assert out["source"] == "local"
    assert out["lines"] == ["line-1", "line-2"]


@pytest.mark.asyncio
async def test_read_ai_extension_logs_payload_falls_back_remote() -> None:
    async def fake_http_json(**kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "url": "http://10.0.0.2:9099/api/ops/logs?kind=celery&n=5",
            "data": {"kind": "celery", "path": "/server/logs/celery.log", "lines": ["worker"], "error": None},
        }

    cfg = {
        "base_url": "http://10.0.0.2:9099",
        "celery_log_file": "/missing/celery.log",
    }
    out = await read_ai_extension_logs_payload(
        cfg,
        "celery",
        5,
        http_json=fake_http_json,
        is_allowed_log_path=lambda path_s: True,
    )
    assert out["source"] == "remote"
    assert out["lines"] == ["worker"]


@pytest.mark.asyncio
async def test_fetch_remote_ai_extension_logs_auth_error() -> None:
    async def unauthorized_http_json(**kwargs: object) -> dict[str, object]:
        return {"ok": False, "status_code": 401, "url": "http://10.0.0.2:9099/api/ops/logs", "data": {}}

    out = await fetch_remote_ai_extension_logs(
        {"base_url": "http://10.0.0.2:9099", "token": "wrong"},
        "uvicorn",
        10,
        http_json=unauthorized_http_json,
    )
    assert out is not None
    assert out["error"] is not None
    assert "鉴权" in out["error"]
