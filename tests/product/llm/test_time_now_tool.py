from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

from pallas.product.llm.tools import registry
from pallas.product.llm.tools.select import infer_tool_domains


def test_time_tool_returns_shanghai_time_and_timestamp() -> None:
    from pallas.product.llm.tools.time_now import handle_time_now

    result = asyncio.run(handle_time_now({}, None))

    assert result["ok"] is True
    payload = result["result"]
    parsed = datetime.fromisoformat(payload["iso"])
    assert payload["timezone"] == "Asia/Shanghai"
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 8 * 3600
    assert payload["timestamp"] == int(parsed.timestamp())
    assert payload["readable"].startswith(str(parsed.year))


def test_time_tool_is_registered_as_read_only_and_selected(monkeypatch) -> None:
    from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped

    monkeypatch.setattr(
        registry,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_tools_enabled=True,
            llm_tools_blacklist=[],
            llm_tools_desc_max_len=120,
            llm_tools_selective=False,
        ),
    )
    ensure_llm_tools_bootstrapped(force=True)

    spec = next(item for item in registry.list_registered_tools() if item.name == "time.now")
    assert spec.parameters == {"type": "object", "properties": {}, "required": []}
    assert spec.read_only is True
    assert "read_only" in spec.capabilities
    assert "time" in infer_tool_domains("现在几点了")
