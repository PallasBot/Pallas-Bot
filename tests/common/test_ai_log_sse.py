"""AI 扩展日志文件尾部读取与 SSE。"""

from __future__ import annotations

import pytest

from pallas.console.web.ai_log_sse import iter_ai_log_file_sse, read_ai_log_chunk


def test_read_ai_log_chunk_tails_and_resumes(tmp_path) -> None:
    log = tmp_path / "app.log"
    log.write_text("line1\nline2\nline3\n", encoding="utf-8")

    offset, lines = read_ai_log_chunk(log, offset=0, initial_tail_bytes=10_000)
    assert lines == ["line1", "line2", "line3"]
    assert offset == log.stat().st_size

    offset2, lines2 = read_ai_log_chunk(log, offset=offset, initial_tail_bytes=0)
    assert lines2 == []
    assert offset2 == offset

    log.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    offset3, lines3 = read_ai_log_chunk(log, offset=offset, initial_tail_bytes=0)
    assert lines3 == ["line4"]
    assert offset3 == log.stat().st_size


def test_read_ai_log_chunk_skips_partial_tail_start(tmp_path) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"0123456789abcdefghij\nkeep-me\n")
    offset, lines = read_ai_log_chunk(log, offset=0, initial_tail_bytes=12)
    assert "keep-me" in lines
    assert not any(line.startswith("0123") for line in lines)
    assert offset == log.stat().st_size


@pytest.mark.asyncio
async def test_iter_ai_log_file_sse_missing_file(tmp_path) -> None:
    missing = tmp_path / "missing.log"
    chunks: list[str] = []
    async for chunk in iter_ai_log_file_sse(missing, kind="uvicorn"):
        chunks.append(chunk)
        break
    assert chunks
    assert '"type": "error"' in chunks[0] or '"type":"error"' in chunks[0]
    assert "不存在" in chunks[0]


@pytest.mark.asyncio
async def test_iter_ai_log_file_sse_ready_and_lines(tmp_path) -> None:
    log = tmp_path / "app.log"
    log.write_text("alpha\nbeta\n", encoding="utf-8")
    chunks: list[str] = []
    async for chunk in iter_ai_log_file_sse(
        log,
        kind="uvicorn",
        poll_interval_sec=0.01,
        initial_tail_bytes=10_000,
    ):
        chunks.append(chunk)
        if len(chunks) >= 3:
            break
    assert any('"type": "ready"' in c or '"type":"ready"' in c for c in chunks)
    joined = "".join(chunks)
    assert "alpha" in joined
    assert "beta" in joined
