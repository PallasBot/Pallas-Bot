from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.greeting import commands


@pytest.mark.asyncio
async def test_to_me_voice_reads_file_in_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    class VoiceFile:
        def read_bytes(self) -> bytes:
            raise AssertionError("voice file must not be read on the event loop")

    class Cooldown:
        async def is_cooldown(self, _name: str) -> bool:
            return True

        async def refresh_cooldown(self, _name: str) -> None:
            return None

    voice_file = VoiceFile()
    to_thread = AsyncMock(return_value=b"voice")
    finish = AsyncMock()
    event = MagicMock(group_id=123, self_id=10001, reply=None)
    event.get_plaintext.return_value = ""
    monkeypatch.setattr(commands, "greeting_plugin_disabled", AsyncMock(return_value=False))
    monkeypatch.setattr(commands, "BotConfig", lambda *_args: Cooldown())
    monkeypatch.setattr(commands, "get_random_voice", lambda *_args: voice_file)
    monkeypatch.setattr(commands.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(commands.to_me_cmd, "finish", finish)

    await commands.handle_to_me(MagicMock(), event)

    to_thread.assert_awaited_once_with(voice_file.read_bytes)
    finish.assert_awaited_once()
