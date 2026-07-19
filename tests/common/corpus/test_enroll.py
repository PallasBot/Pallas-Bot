from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pallas.product.community_stats.endpoints import FALLBACK_HEARTBEAT, PRIMARY_HEARTBEAT
from pallas.product.community_stats.store import community_stats_state_path
from pallas.product.corpus.enroll import enroll_url_from_heartbeat, ensure_corpus_community_enrolled
from pallas.product.corpus.store import load_corpus_community_state


@pytest.fixture(autouse=True)
def clear_corpus_config():
    from pallas.product.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    yield
    clear_corpus_config_cache()


def test_enroll_url_from_heartbeat():
    assert enroll_url_from_heartbeat(PRIMARY_HEARTBEAT) == "https://stats.pallasbot.top/v1/corpus/enroll"


@pytest.mark.asyncio
async def test_ensure_corpus_community_enrolled_persists_token(tmp_path, monkeypatch):
    state_path = tmp_path / "data" / "pallas_config" / "community_stats.json"
    dep = str(uuid.uuid4())
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"deployment_id": dep}), encoding="utf-8")
    monkeypatch.setattr("pallas.product.community_stats.store.community_stats_state_path", lambda: state_path)

    monkeypatch.setattr(
        "pallas.product.corpus.enroll.should_run_corpus_auto_enroll",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.product.corpus.enroll.corpus_enroll_urls",
        lambda: ["https://stats.example/v1/corpus/enroll"],
    )

    response = httpx.Response(
        200,
        json={
            "corpus_token": "pc_testtoken",
            "api_base": "https://stats.example/v1/corpus",
            "policy": {"read": True, "contribute": False},
        },
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
        ok = await ensure_corpus_community_enrolled()

    assert ok is True
    saved = load_corpus_community_state()
    assert saved["corpus_token"] == "pc_testtoken"
    assert saved["api_base"] == "https://stats.example/v1/corpus"
    assert community_stats_state_path().is_file()


@pytest.mark.asyncio
async def test_enroll_prefers_derived_api_base_in_auto_mode(tmp_path, monkeypatch):
    state_path = tmp_path / "data" / "pallas_config" / "community_stats.json"
    dep = str(uuid.uuid4())
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"deployment_id": dep}), encoding="utf-8")
    monkeypatch.setattr("pallas.product.community_stats.store.community_stats_state_path", lambda: state_path)
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    monkeypatch.setattr("pallas.product.corpus.enroll.should_run_corpus_auto_enroll", lambda: True)
    monkeypatch.setattr(
        "pallas.product.corpus.enroll.corpus_enroll_urls",
        lambda: [f"{FALLBACK_HEARTBEAT.replace('/heartbeat', '/corpus/enroll')}"],
    )

    response = httpx.Response(
        200,
        json={
            "corpus_token": "pc_testtoken",
            "api_base": "https://stats.pallasbot.top/v1/corpus",
            "policy": {"read": True, "contribute": True},
        },
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
        ok = await ensure_corpus_community_enrolled()

    assert ok is True
    saved = load_corpus_community_state()
    assert saved["api_base"] == "https://pallas.togetsudo.com/v1/corpus"


@pytest.mark.asyncio
async def test_ensure_corpus_skips_when_manual_configured(monkeypatch):
    monkeypatch.setattr("pallas.product.corpus.enroll.community_manual_configured", lambda: True)
    monkeypatch.setattr("pallas.product.corpus.enroll.should_run_corpus_auto_enroll", lambda: False)
    monkeypatch.setattr(
        "pallas.product.corpus.config.community_configured",
        lambda: True,
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        ok = await ensure_corpus_community_enrolled(force=True)
    assert ok is True
    mock_post.assert_not_called()
