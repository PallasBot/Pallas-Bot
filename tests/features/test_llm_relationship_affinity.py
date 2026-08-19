from __future__ import annotations

from pallas.product.llm.config import LlmConfig


def test_affinity_config_defaults() -> None:
    cfg = LlmConfig()
    assert cfg.llm_relationship_affinity_enabled is True
    assert cfg.llm_relationship_affinity_delta_max == 0.15
    assert cfg.llm_relationship_affinity_llm_cooldown_s == 60
    assert cfg.llm_relationship_affinity_daily_decay_step == 0.02
    assert cfg.llm_relationship_affinity_silence_threshold == -0.3
    assert cfg.llm_relationship_affinity_silence_max_penalty == 30
