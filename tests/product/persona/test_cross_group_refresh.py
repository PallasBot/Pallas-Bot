from __future__ import annotations

import pytest

from pallas.product.persona.cross_group_refresh import refresh_bot_cross_group_persona


@pytest.mark.asyncio
async def test_cross_group_refresh_preserves_explicit_account_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored_persona = {
        "account_profile": {
            "source": "manual",
            "energy": 0.3,
            "warmth": 0.4,
            "mischief": 0.0,
            "restraint": 0.0,
        },
        "self_aliases": ["猪猪"],
    }
    written: dict[str, object] = {}

    class MessageRepo:
        async def list_recent_group_ids_for_bot(self, bot_id, *, since_time, limit):  # noqa: ARG002
            return []

    class GroupRepo:
        async def get(self, group_id):  # noqa: ARG002
            return None

    class BotRepo:
        async def get(self, bot_id):  # noqa: ARG002
            return type("BotConfig", (), {"persona": stored_persona})()

        async def upsert_field(self, bot_id, field, value):  # noqa: ARG002
            written[field] = value

    monkeypatch.setattr(
        "pallas.product.persona.cross_group_refresh.make_message_repository",
        lambda: MessageRepo(),
    )
    monkeypatch.setattr(
        "pallas.product.persona.cross_group_refresh.make_group_config_repository",
        lambda: GroupRepo(),
    )
    monkeypatch.setattr(
        "pallas.product.persona.cross_group_refresh.make_bot_config_repository",
        lambda: BotRepo(),
    )
    monkeypatch.setattr(
        "pallas.product.persona.cross_group_refresh.build_bot_cross_group_persona",
        lambda **kwargs: {
            "source": "cross_group_expression",
            "aggregate": {"sample_count": 0},
            "reply_shape": {"length_pref": "any"},
            "summary": {"group_count": 0},
        },
    )

    assert await refresh_bot_cross_group_persona(7)
    assert written["persona"]["account_profile"] == stored_persona["account_profile"]
    assert written["persona"]["self_aliases"] == ["猪猪"]
    assert written["persona"]["cross_group_expression"]["source"] == "cross_group_expression"
