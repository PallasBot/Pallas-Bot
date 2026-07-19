from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from pallas.core.shared.utils import stream_download
from pallas.core.shared.utils.stream_download import format_download_byte_size, sync_stream_download_to_file


class _FakeStreamCtx:
    def __init__(self, chunks: list[bytes], content_length: int | None, *, boom_after_chunks: int | None = None):
        self.headers: dict[str, str] = {}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self._chunks = chunks
        self._boom_after_chunks = boom_after_chunks

    def __enter__(self) -> _FakeStreamCtx:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self, chunk_size: int = 8192) -> Iterator[bytes]:
        for i, chunk in enumerate(self._chunks, start=1):
            yield chunk
            if self._boom_after_chunks is not None and i >= self._boom_after_chunks:
                raise RuntimeError("boom")


class _FakeHttpClientCtx:
    def __init__(self, stream: _FakeStreamCtx):
        self._stream = stream

    def __enter__(self) -> _FakeHttpClientCtx:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def stream(self, _method: str, _url: str, **_kwargs: Any) -> _FakeStreamCtx:
        return self._stream


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, stream: _FakeStreamCtx) -> None:
    def _client_factory(**_kwargs: Any) -> _FakeHttpClientCtx:
        return _FakeHttpClientCtx(stream)

    monkeypatch.setattr(stream_download.httpx, "Client", _client_factory)


def test_sync_stream_download_with_content_length_percent_milestones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    total_size = 10 * 1024
    chunk = b"x" * 1024
    chunks = [chunk] * 10
    stream = _FakeStreamCtx(chunks, total_size)
    _patch_httpx_client(monkeypatch, stream)

    events: list[dict[str, Any]] = []
    dest = tmp_path / "out.bin"
    sync_stream_download_to_file(
        "https://example.com/file.bin",
        dest,
        progress_percent_step=10,
        progress_bytes_step=1024,
        on_progress=lambda ev: events.append(dict(ev)),
    )

    assert dest.is_file()
    assert dest.stat().st_size == total_size
    assert not dest.with_name(dest.name + ".download").exists()

    percent_events = [e for e in events if e["event"] == "percent"]
    assert [e["milestone_percent"] for e in percent_events] == [10, 20, 30, 40, 50, 60, 70, 80, 90]

    complete_events = [e for e in events if e["event"] == "complete"]
    assert len(complete_events) == 1
    assert complete_events[0]["received"] == total_size
    assert complete_events[0]["total"] == total_size


def test_sync_stream_download_without_content_length_unknown_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = b"y" * 1024
    chunks = [chunk] * 5
    stream = _FakeStreamCtx(chunks, None)
    _patch_httpx_client(monkeypatch, stream)

    events: list[dict[str, Any]] = []
    dest = tmp_path / "out.bin"
    sync_stream_download_to_file(
        "https://example.com/file.bin",
        dest,
        progress_percent_step=10,
        progress_bytes_step=1024,
        on_progress=lambda ev: events.append(dict(ev)),
    )

    assert dest.stat().st_size == 5 * 1024
    unknown_events = [e for e in events if e["event"] == "unknown_step"]
    assert [e["received"] for e in unknown_events] == [1024, 2048, 3072, 4096, 5120]

    complete_events = [e for e in events if e["event"] == "complete"]
    assert len(complete_events) == 1
    assert complete_events[0]["received"] == 5 * 1024
    assert complete_events[0]["total"] is None


def test_sync_stream_download_failure_removes_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chunk = b"z" * 1024
    stream = _FakeStreamCtx([chunk, chunk], content_length=2048, boom_after_chunks=1)
    _patch_httpx_client(monkeypatch, stream)

    dest = tmp_path / "out.bin"
    part = dest.with_name(dest.name + ".download")
    with pytest.raises(RuntimeError, match="boom"):
        sync_stream_download_to_file("https://example.com/file.bin", dest, on_progress=lambda _ev: None)

    assert not dest.exists()
    assert not part.exists()


@pytest.mark.parametrize(
    ("num_bytes", "expected_substrings"),
    [
        (0, ("0", "B")),
        (1, ("1", "B")),
        (1023, ("1023", "B")),
        (1024, ("1.0", "KiB")),
        (1536, ("1.5", "KiB")),
        (1024 * 1024, ("1.0", "MiB")),
    ],
)
def test_format_download_byte_size(num_bytes: int, expected_substrings: tuple[str, ...]) -> None:
    got = format_download_byte_size(num_bytes)
    for frag in expected_substrings:
        assert frag in got
