import pytest

from src.features.service_gateways.llm_probe import LLM_CATEGORY, probe_llm_service
from src.features.service_gateways.registry import registered_service_probe_names


@pytest.mark.asyncio
async def test_probe_llm_when_all_switches_off(monkeypatch) -> None:
    class FakeCfg:
        llm_chat_enabled = False
        llm_fallback_enabled = False
        llm_polish_enabled = False

    monkeypatch.setattr("src.features.llm.config.get_llm_config", lambda: FakeCfg())
    results = await probe_llm_service(timeout_sec=5.0)
    assert len(results) == 1
    assert results[0].category == LLM_CATEGORY
    assert results[0].ok is False
    assert "均为关" in (results[0].error or "")


def test_llm_provider_registered() -> None:
    assert "llm" in registered_service_probe_names()
    assert "media" in registered_service_probe_names()
