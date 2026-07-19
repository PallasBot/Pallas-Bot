"""语音资源 ensure：冷启动不得阻塞 NoneBot on_startup。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pallas.core.shared.utils import voice_downloader as vd

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def voice_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    resource = tmp_path / "resource"
    resource.mkdir()
    monkeypatch.setattr(vd, "RESOURCE_ROOT", resource)
    monkeypatch.setattr(vd, "VOICES_DIR", resource / "voices")
    monkeypatch.setattr(vd, "TEMP_ZIP_PATH", resource / "voices_temp.zip")
    monkeypatch.setattr(vd, "_background_ensure_task", None, raising=False)
    return resource


def test_voices_ready_false_when_missing(voice_tmp: Path) -> None:
    assert vd.voices_ready() is False


def test_voices_ready_true_when_complete(voice_tmp: Path) -> None:
    pallas = voice_tmp / "voices" / "Pallas"
    pallas.mkdir(parents=True)
    for name in vd.VOICES:
        (pallas / f"{name}.wav").write_bytes(b"x")
    assert vd.voices_ready() is True


@pytest.mark.asyncio
async def test_schedule_ensure_voices_skips_when_ready(voice_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pallas = voice_tmp / "voices" / "Pallas"
    pallas.mkdir(parents=True)
    for name in vd.VOICES:
        (pallas / f"{name}.wav").write_bytes(b"x")

    called = AsyncMock(return_value=True)
    monkeypatch.setattr(vd, "ensure_voices", called)

    vd.schedule_ensure_voices()
    await asyncio.sleep(0)
    called.assert_not_called()
    assert vd._background_ensure_task is None


@pytest.mark.asyncio
async def test_schedule_ensure_voices_runs_in_background(voice_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    finished = asyncio.Event()

    async def slow_ensure(**_kwargs: object) -> bool:
        started.set()
        await finished.wait()
        return True

    monkeypatch.setattr(vd, "ensure_voices", slow_ensure)

    # schedule must return before ensure completes (non-blocking)
    vd.schedule_ensure_voices()
    assert vd._background_ensure_task is not None
    assert not vd._background_ensure_task.done()

    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert not vd._background_ensure_task.done()

    finished.set()
    await asyncio.wait_for(vd._background_ensure_task, timeout=1.0)
    assert vd._background_ensure_task.done()
