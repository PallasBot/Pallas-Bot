from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.governance import (
    is_llm_chat_group_allowed,
    llm_chat_concurrency_limit,
    parse_group_id_set,
)


def test_parse_group_id_set_csv_and_json() -> None:
    assert parse_group_id_set("100,200") == {100, 200}
    assert parse_group_id_set("[300, 400]") == {300, 400}


def test_group_allowlist_respects_disabled_ids() -> None:
    cfg = LlmConfig(llm_chat_disabled_group_ids=[12345])
    assert is_llm_chat_group_allowed(12345, cfg=cfg) is False
    assert is_llm_chat_group_allowed(99999, cfg=cfg) is True


def test_concurrency_respects_configured_limit() -> None:
    cfg = LlmConfig(llm_chat_max_concurrency=2)
    assert llm_chat_concurrency_limit(cfg) <= 2


@pytest.mark.asyncio
async def test_check_llm_chat_gate_disabled_by_default() -> None:
    clear_llm_config_cache()
    from pallas.product.llm.governance import check_llm_chat_gate

    assert await check_llm_chat_gate(object(), 10001) is None
