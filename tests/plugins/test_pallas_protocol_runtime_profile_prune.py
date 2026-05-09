"""runtime_profile 保存与容器清理范围。"""

from __future__ import annotations

import json

import pytest

from src.plugins.pallas_protocol.config import Config
from src.plugins.pallas_protocol.service import PallasProtocolService


@pytest.mark.asyncio
async def test_update_runtime_profile_mode_change_disallows_partial_prune(tmp_path) -> None:
    data = tmp_path / "pdata"
    data.mkdir()
    prof = {
        "runtime_mode": "shell",
        "target_platform": "auto",
        "docker_image": "mlikiowa/napcat-docker:latest",
        "snowluma_docker_image": "motricseven7/snowluma:latest",
        "follow_bot_lifecycle": True,
    }
    (data / "runtime_profile.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    (data / "accounts.json").write_text("{}", encoding="utf-8")
    svc = PallasProtocolService(data, Config())
    with pytest.raises(ValueError, match="须选择「NapCat 与 SnowLuma 全部」"):
        await svc.update_runtime_profile({**prof, "runtime_mode": "docker", "prune_containers": "snowluma"})


@pytest.mark.asyncio
async def test_update_runtime_profile_passes_prune_scope_when_mode_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    data = tmp_path / "pdata2"
    data.mkdir()
    prof = {
        "runtime_mode": "docker",
        "target_platform": "auto",
        "docker_image": "mlikiowa/napcat-docker:latest",
        "snowluma_docker_image": "motricseven7/snowluma:latest",
        "follow_bot_lifecycle": True,
    }
    (data / "runtime_profile.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    (data / "accounts.json").write_text("{}", encoding="utf-8")
    svc = PallasProtocolService(data, Config())
    called: list[str] = []

    async def capture(*, prune_containers: str = "all") -> None:
        called.append(prune_containers)

    monkeypatch.setattr(
        svc,
        "_prune_all_protocol_docker_containers_after_runtime_profile_change",
        capture,
    )
    await svc.update_runtime_profile(
        {**prof, "snowluma_docker_image": "motricseven7/snowluma:edge", "prune_containers": "snowluma"},
    )
    assert called == ["snowluma"]


@pytest.mark.asyncio
async def test_update_runtime_profile_napcat_docker_flip_allows_napcat_prune_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    data = tmp_path / "pdata_split"
    data.mkdir()
    prof = {
        "runtime_mode": "shell",
        "napcat_runtime_mode": "shell",
        "snowluma_runtime_mode": "docker",
        "target_platform": "auto",
        "docker_image": "mlikiowa/napcat-docker:latest",
        "snowluma_docker_image": "motricseven7/snowluma:latest",
        "follow_bot_lifecycle": True,
    }
    (data / "runtime_profile.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    (data / "accounts.json").write_text("{}", encoding="utf-8")
    svc = PallasProtocolService(data, Config())
    called: list[str] = []

    async def capture(*, prune_containers: str = "all") -> None:
        called.append(prune_containers)

    monkeypatch.setattr(
        svc,
        "_prune_all_protocol_docker_containers_after_runtime_profile_change",
        capture,
    )
    await svc.update_runtime_profile(
        {
            **prof,
            "napcat_runtime_mode": "docker",
            "snowluma_runtime_mode": "docker",
            "prune_containers": "napcat",
        },
    )
    assert called == ["napcat"]
