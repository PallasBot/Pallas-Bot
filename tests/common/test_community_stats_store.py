from __future__ import annotations

import time
from pathlib import Path

import pytest

from pallas.product.community_stats import store as stats_store


@pytest.fixture
def community_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "community_stats.json"
    monkeypatch.setattr(stats_store, "community_stats_state_path", lambda: path)
    stats_store.reset_community_stats_state_cache_for_tests()
    return path


def test_load_or_create_deployment_id_reuses_cached_state(
    community_state_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    community_state_file.write_text('{"deployment_id":"123e4567-e89b-12d3-a456-426614174000"}', encoding="utf-8")
    real_read_text = Path.read_text
    reads = 0

    def spy_read_text(self: Path, *args, **kwargs):
        nonlocal reads
        if self == community_state_file:
            reads += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)

    assert stats_store.load_or_create_deployment_id() == "123e4567-e89b-12d3-a456-426614174000"
    assert stats_store.load_or_create_deployment_id() == "123e4567-e89b-12d3-a456-426614174000"
    assert reads == 1


def test_load_community_stats_state_refreshes_when_file_changes(
    community_state_file: Path,
) -> None:
    community_state_file.write_text('{"deployment_id":"deploy-a"}', encoding="utf-8")

    first = stats_store.load_community_stats_state()
    time.sleep(0.01)
    community_state_file.write_text('{"deployment_id":"deploy-b","federate_id":"fed-b"}', encoding="utf-8")
    second = stats_store.load_community_stats_state()

    assert first["deployment_id"] == "deploy-a"
    assert second["deployment_id"] == "deploy-b"
    assert second["federate_id"] == "fed-b"
