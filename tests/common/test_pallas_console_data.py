from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_database_overview_pg_uses_estimates_for_large_tables(monkeypatch):
    from pallas.core.foundation.db import pallas_console_data as mod

    exact_models: list[type] = []
    estimated_models: list[type] = []

    class BotConfigRow:
        pass

    class GroupConfigRow:
        pass

    class UserConfigRow:
        pass

    class MessageRow:
        pass

    class ContextRow:
        pass

    class ContextAnswerRow:
        pass

    class ContextAnswerMessageRow:
        pass

    class ContextBanRow:
        pass

    class BlackListRow:
        pass

    class ImageCacheRow:
        pass

    async def fake_pg_estimate_row_count(model: type) -> int:
        estimated_models.append(model)
        values = {
            MessageRow: 1001,
            ContextRow: 1002,
            ContextAnswerRow: 1004,
            ContextAnswerMessageRow: 1005,
            ContextBanRow: 1006,
            ImageCacheRow: 1003,
        }
        return values[model]

    async def fake_pg_exact_row_count(model: type) -> int:
        exact_models.append(model)
        values = {
            BotConfigRow: 11,
            GroupConfigRow: 22,
            UserConfigRow: 33,
            BlackListRow: 44,
        }
        return values[model]

    monkeypatch.setattr(mod, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(mod, "_pg_estimate_row_count", fake_pg_estimate_row_count)
    monkeypatch.setattr(mod, "_pg_exact_row_count", fake_pg_exact_row_count)

    import pallas.core.foundation.db.repository_pg as repo_pg

    monkeypatch.setattr(repo_pg, "BotConfigRow", BotConfigRow)
    monkeypatch.setattr(repo_pg, "GroupConfigRow", GroupConfigRow)
    monkeypatch.setattr(repo_pg, "UserConfigRow", UserConfigRow)
    monkeypatch.setattr(repo_pg, "MessageRow", MessageRow)
    monkeypatch.setattr(repo_pg, "ContextRow", ContextRow)
    monkeypatch.setattr(repo_pg, "ContextAnswerRow", ContextAnswerRow)
    monkeypatch.setattr(repo_pg, "ContextAnswerMessageRow", ContextAnswerMessageRow)
    monkeypatch.setattr(repo_pg, "ContextBanRow", ContextBanRow)
    monkeypatch.setattr(repo_pg, "BlackListRow", BlackListRow)
    monkeypatch.setattr(repo_pg, "ImageCacheRow", ImageCacheRow)

    data = await mod.database_overview()

    assert data["backend"] == "postgres"
    assert data["tables"] == [
        {"table": "bot_config", "count": 11, "count_estimated": False},
        {"table": "group_config", "count": 22, "count_estimated": False},
        {"table": "user_config", "count": 33, "count_estimated": False},
        {"table": "message", "count": 1001, "count_estimated": True},
        {"table": "context", "count": 1002, "count_estimated": True},
        {"table": "context_answer", "count": 1004, "count_estimated": True},
        {"table": "context_answer_message", "count": 1005, "count_estimated": True},
        {"table": "context_ban", "count": 1006, "count_estimated": True},
        {"table": "blacklist", "count": 44, "count_estimated": False},
        {"table": "image_cache", "count": 1003, "count_estimated": True},
    ]
    assert exact_models == [BotConfigRow, GroupConfigRow, UserConfigRow, BlackListRow]
    assert estimated_models == [
        MessageRow,
        ContextRow,
        ContextAnswerRow,
        ContextAnswerMessageRow,
        ContextBanRow,
        ImageCacheRow,
    ]


@pytest.mark.asyncio
async def test_database_tables_view_marks_corpus_child_tables_overview_only(monkeypatch):
    from pallas.core.foundation.db import pallas_console_data as mod

    async def fake_overview() -> dict:
        return {
            "backend": "postgres",
            "tables": [
                {"table": "context", "count": 10, "count_estimated": True},
                {"table": "context_answer", "count": 20, "count_estimated": True},
                {"table": "context_answer_message", "count": 30, "count_estimated": True},
                {"table": "context_ban", "count": 4, "count_estimated": True},
                {"table": "bot_config", "count": 1, "count_estimated": False},
            ],
        }

    monkeypatch.setattr(mod, "database_overview", fake_overview)
    data = await mod.database_tables_view()
    by_name = {t["name"]: t for t in data["tables"]}
    assert by_name["context_answer"]["overview_only"] is True
    assert by_name["context_answer"]["browseable"] is False
    assert by_name["context_answer_message"]["overview_only"] is True
    assert by_name["context_ban"]["overview_only"] is True
    assert by_name["bot_config"]["browseable"] is True
    assert by_name["bot_config"]["overview_only"] is False


def test_group_config_to_public_includes_style_profile_snapshot() -> None:
    from types import SimpleNamespace

    from pallas.core.foundation.db.pallas_console_data import group_config_to_public

    row = SimpleNamespace(
        group_id=12345,
        roulette_mode=1,
        banned=False,
        sing_progress=None,
        disabled_plugins=[],
        blocked_user_ids=[],
        style_profile={
            "updated_at": 1_700_000_000,
            "derived": {
                "length_pref": "short",
                "reply_bias_mul": 1.05,
                "chaos_bias": 0.12,
            },
            "raw": {"avg_plain_len": 8.0},
            "sample": {"message_count": 40},
        },
    )
    payload = group_config_to_public(row)
    snapshot = payload["style_profile_snapshot"]
    assert snapshot["ready"] is True
    assert snapshot["signals"]["length_pref"] == "short"
    assert snapshot["hints"]
