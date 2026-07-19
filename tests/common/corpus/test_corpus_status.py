from __future__ import annotations

import pytest

from pallas.product.corpus.status import build_corpus_status_snapshot


async def _mock_no_usage():
    return None


@pytest.mark.asyncio
async def test_build_corpus_status_snapshot_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "pallas.product.corpus.usage.fetch_corpus_community_usage",
        _mock_no_usage,
    )
    monkeypatch.setattr(
        "pallas.product.corpus.status.load_corpus_community_state",
        lambda: {
            "api_base": "https://stats.example/v1/corpus",
            "corpus_token": "pc_test",
            "contribute": False,
            "enrolled_at": 1_700_000_000,
        },
    )
    monkeypatch.setattr("pallas.product.corpus.status.corpus_community_enrollment_valid", lambda _state=None: True)
    monkeypatch.setattr("pallas.product.corpus.status.community_manual_configured", lambda: False)
    monkeypatch.setattr("pallas.product.corpus.status.fed_configured", lambda: False)
    monkeypatch.setattr("pallas.product.corpus.status.community_configured", lambda: True)
    monkeypatch.setattr("pallas.product.corpus.config.community_configured", lambda: True)
    monkeypatch.setattr(
        "pallas.product.corpus.config.repo_env_raw_value",
        lambda name: (
            "true"
            if name == "PALLAS_CORPUS_COMMUNITY_ENABLED"
            else ("false" if name == "PALLAS_CORPUS_AUTO_ENROLL" else None)
        ),
    )
    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    snap = await build_corpus_status_snapshot()
    assert snap["composite_active"] is True
    assert snap["remote_find_mode"] in {"off", "sync", "prefetch"}
    assert snap["sources"]["local"]["enabled"] is True
    assert snap["sources"]["community"]["enrolled"] is True
    assert snap["sources"]["community"]["contribute"] is False
    assert snap["sources"]["community"]["token_present"] is True
    assert snap["sources"]["community"]["usage"] is None
    assert "deployment_id" in snap["deployment"]


@pytest.mark.asyncio
async def test_build_corpus_status_snapshot_keeps_persisted_community_off_by_default(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.corpus.status.load_corpus_community_state",
        lambda: {
            "api_base": "https://stats.example/v1/corpus",
            "corpus_token": "pc_test",
            "contribute": False,
            "enrolled_at": 1_700_000_000,
        },
    )
    monkeypatch.setattr("pallas.product.corpus.status.corpus_community_enrollment_valid", lambda _state=None: True)
    monkeypatch.setattr("pallas.product.corpus.status.community_manual_configured", lambda: False)
    monkeypatch.setattr("pallas.product.corpus.status.fed_configured", lambda: False)
    monkeypatch.setattr(
        "pallas.product.corpus.config.repo_env_raw_value",
        lambda name: "auto" if name == "PALLAS_CORPUS_COMMUNITY_ENABLED" else None,
    )
    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    snap = await build_corpus_status_snapshot()
    assert snap["composite_active"] is False
    assert snap["sources"]["community"]["enabled"] is False
    assert snap["sources"]["community"]["wanted"] is False
    assert snap["sources"]["community"]["readable"] is False


@pytest.mark.asyncio
async def test_build_corpus_status_snapshot_exposes_bootstrap_corpus_community(monkeypatch):
    monkeypatch.setattr("pallas.product.corpus.status.load_corpus_community_state", dict)
    monkeypatch.setattr("pallas.product.corpus.status.corpus_community_enrollment_valid", lambda _state=None: False)
    monkeypatch.setattr("pallas.product.corpus.status.community_manual_configured", lambda: False)
    monkeypatch.setattr("pallas.product.corpus.status.fed_configured", lambda: False)
    monkeypatch.setattr(
        "pallas.product.corpus.config.repo_env_raw_value",
        lambda name: "false" if name == "PALLAS_CORPUS_COMMUNITY_ENABLED" else None,
    )

    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()

    def fake_read_state_raw():
        return {
            "federate_id": "pool-a",
            "control_plane_bootstrap": {
                "fetched_at": 1_700_000_000,
                "expires_at": 1_800_000_000,
                "corpus_community": {
                    "api_base": "https://stats.example/v1/corpus",
                    "readable": True,
                    "writable": False,
                },
            },
        }

    monkeypatch.setattr("pallas.product.community_stats.store._read_state_raw", fake_read_state_raw)

    snap = await build_corpus_status_snapshot()

    assert snap["control_plane"]["bootstrap_federate_id"] == "pool-a"
    assert snap["control_plane"]["bootstrap_corpus_community"]["api_base"] == "https://stats.example/v1/corpus"
    assert snap["control_plane"]["bootstrap_corpus_community"]["readable"] is True
