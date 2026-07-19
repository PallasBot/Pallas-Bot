from __future__ import annotations

import pytest

from pallas.product.persona.model import ResolvedPersona
from pallas.product.persona.observe import (
    behavior_hint_lines,
    build_persona_observe_payload,
    parse_observe_accounts,
    persona_axis_snapshot,
)


def test_parse_observe_accounts() -> None:
    assert parse_observe_accounts(None) is None
    assert parse_observe_accounts("") is None
    assert parse_observe_accounts("10001, 10002,10001") == [10001, 10002]


def test_persona_axis_snapshot_fields() -> None:
    persona = ResolvedPersona(warmth=0.12, assertiveness=-0.08, bluntness=0.05, archetype="terse")
    snap = persona_axis_snapshot(persona)
    assert snap["warmth"] == pytest.approx(0.12)
    assert snap["archetype"] == "terse"


def test_behavior_hint_lines_not_empty_for_mid_warmth() -> None:
    persona = ResolvedPersona(warmth=0.05, assertiveness=0.0, bluntness=0.0)
    hints = behavior_hint_lines(persona)
    assert any("中性" in line for line in hints)


@pytest.mark.asyncio
async def test_build_persona_observe_payload_without_group(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list() -> list[dict]:
        return [{"account": 10001, "group_style_enabled": True}]

    async def fake_resolve(bot_id: int, group_id: int | None = None) -> ResolvedPersona:
        return ResolvedPersona(warmth=0.05)

    monkeypatch.setattr(
        "pallas.core.foundation.db.pallas_console_data.list_all_bot_configs_public",
        fake_list,
    )
    monkeypatch.setattr("pallas.product.persona.observe.resolve_persona", fake_resolve)

    payload = await build_persona_observe_payload(group_id=None, accounts=[10001])
    assert payload["group_id"] is None
    assert len(payload["bots"]) == 1
    assert payload["bots"][0]["resolved"] is None
    assert payload["bots"][0]["base"]["warmth"] == pytest.approx(0.05)
