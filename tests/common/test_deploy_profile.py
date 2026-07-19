"""deploy_profile 与 apply_deploy_profile 工具。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pallas.core.foundation.deploy_profile import (
    clear_deploy_profile_cache,
    is_deploy_profile_active,
    read_profile_env_fragment,
    record_deploy_profile,
    uv_sync_hint_for_profile,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def reset_deploy_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    marker = tmp_path / "deploy_profiles.json"
    monkeypatch.setattr(
        "pallas.core.foundation.deploy_profile.DEPLOY_MARKER_PATH",
        marker,
    )
    clear_deploy_profile_cache()
    yield
    clear_deploy_profile_cache()


def test_read_shard_fragment_has_shard_enabled() -> None:
    env = read_profile_env_fragment("shard")
    assert env.get("PALLAS_SHARD_ENABLED") == "true"


def test_record_deploy_profile_merges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "deploy_profiles.json"
    monkeypatch.setattr("pallas.core.foundation.deploy_profile.DEPLOY_MARKER_PATH", marker)
    clear_deploy_profile_cache()
    record_deploy_profile("shard")
    record_deploy_profile("shard")
    clear_deploy_profile_cache()
    assert is_deploy_profile_active("shard")
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert "deploy-shard" in data["extras"]


def test_uv_sync_hint_shard() -> None:
    assert "deploy-shard" in uv_sync_hint_for_profile("shard")
