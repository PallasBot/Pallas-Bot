from __future__ import annotations

import pytest

from src.plugins.pallas_protocol.config import Config
from src.plugins.pallas_protocol.service import PallasProtocolService


@pytest.mark.asyncio
async def test_remove_linux_docker_containers_for_protocol_switch_calls_both_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    removed: list[str] = []

    async def capture_rm(name: str) -> None:
        removed.append(name)

    monkeypatch.setattr(
        "src.plugins.pallas_protocol.linux_docker.docker_remove_force",
        capture_rm,
    )
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.snowluma_docker.snowluma_docker_remove_force",
        capture_rm,
    )

    svc = PallasProtocolService(tmp_path / "pd", Config())
    await svc._remove_both_linux_docker_container_names_for_account({"id": "30111222"})
    assert "pallas-proto-30111222" in removed
    assert "pallas-proto-sl-30111222" in removed
