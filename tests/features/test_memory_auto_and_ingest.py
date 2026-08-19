"""启发式 auto_episode 与 file ingest。"""

from __future__ import annotations

import asyncio
import json

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.file_ingest import (
    ensure_file_knowledge_registered,
    load_file_knowledge_decl,
    reset_file_knowledge_registration_for_tests,
)
from pallas.product.llm.memory.auto_episode import (
    clear_auto_episode_cooldown_for_tests,
    maybe_auto_save_episode,
    maybe_auto_save_group_episode,
)
from pallas.product.llm.session_models import LlmChatTurn


def message_repo(fetch):
    class Repo:
        async def find_recent_in_group(self, group_id: int, *, limit: int):  # noqa: ARG002
            return await fetch()

    return Repo()


@pytest.mark.asyncio
async def test_auto_episode_skips_low_value(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    called = {"n": 0}

    async def fake_save(*_a, **_k):
        called["n"] += 1
        return True

    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.is_llm_memory_store_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)
    cfg = LlmConfig(llm_memory_auto_episode_enabled=True, llm_memory_auto_episode_cooldown_sec=0)
    assert await maybe_auto_save_episode(bot_id=1, group_id=2, user_text="好烦", cfg=cfg) is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_auto_episode_saves_valuable_note(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    called: dict[str, str] = {}

    async def fake_save(_bot, _gid, content, *, source="teach", cfg=None):
        called["content"] = content
        called["source"] = source
        return True

    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.is_llm_memory_store_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)
    cfg = LlmConfig(llm_memory_auto_episode_enabled=True, llm_memory_auto_episode_cooldown_sec=0)
    ok = await maybe_auto_save_episode(
        bot_id=1,
        group_id=2,
        user_text="记住：本群周五固定开黑",
        cfg=cfg,
    )
    assert ok is True
    assert called["source"] == "auto_episode"
    assert "开黑" in called["content"]


@pytest.mark.asyncio
async def test_auto_episode_summarizes_shared_group_event(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    saved: dict[str, str] = {}

    async def fake_list(*_args, **_kwargs):
        return [
            LlmChatTurn(role="user", content="周五晚上一起开黑吗", user_id=11, created_at=1),
            LlmChatTurn(role="user", content="可以，我带新图", user_id=22, created_at=2),
            LlmChatTurn(role="assistant", content="那就周五见", user_id=1, created_at=3),
            LlmChatTurn(role="user", content="八点在群里喊", user_id=11, created_at=4),
        ]

    async def fake_complete(*_args, **_kwargs):
        return {"content": "群友约定周五晚上八点在群里开黑，由一名群友带新图"}

    async def fake_save(_bot, _gid, content, *, source="teach", cfg=None):
        saved["content"] = content
        saved["source"] = source
        return True

    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.make_message_repository", lambda: message_repo(fake_list)
    )
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.complete_chat_message", fake_complete)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)

    cfg = LlmConfig(
        llm_memory_auto_episode_enabled=True,
        llm_memory_auto_episode_summary_enabled=True,
        llm_memory_auto_episode_cooldown_sec=0,
    )
    assert await maybe_auto_save_group_episode(bot_id=1, group_id=2, cfg=cfg) is True
    assert saved["source"] == "auto_episode_summary"
    assert saved["content"] == "群友约定周五晚上八点在群里开黑，由一名群友带新图"


@pytest.mark.asyncio
async def test_auto_episode_summary_runs_once_while_group_summary_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_auto_episode_cooldown_for_tests()
    complete_calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_list(*_args, **_kwargs):
        return [
            LlmChatTurn(role="user", content="周五晚上一起开黑吗", user_id=11, created_at=1),
            LlmChatTurn(role="user", content="可以，我带新图", user_id=22, created_at=2),
            LlmChatTurn(role="user", content="八点在群里喊", user_id=11, created_at=3),
        ]

    async def fake_complete(*_args, **_kwargs):
        nonlocal complete_calls
        complete_calls += 1
        started.set()
        await release.wait()
        return {"content": "群友约定周五晚上八点在群里开黑"}

    async def fake_save(*_args, **_kwargs):
        return True

    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.make_message_repository", lambda: message_repo(fake_list)
    )
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.complete_chat_message", fake_complete)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)
    cfg = LlmConfig(llm_memory_auto_episode_enabled=True, llm_memory_auto_episode_summary_enabled=True)

    first = asyncio.create_task(maybe_auto_save_group_episode(bot_id=1, group_id=2, cfg=cfg))
    await started.wait()
    second = asyncio.create_task(maybe_auto_save_group_episode(bot_id=1, group_id=2, cfg=cfg))
    try:
        await asyncio.sleep(0)
        assert complete_calls == 1
    finally:
        release.set()
    assert await first is True
    assert await second is False


@pytest.mark.asyncio
async def test_auto_episode_summary_rejects_future_behavior_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    saved = {"count": 0}

    async def fake_list(*_args, **_kwargs):
        return [
            LlmChatTurn(role="user", content="周五晚上一起开黑吗", user_id=11, created_at=1),
            LlmChatTurn(role="user", content="可以，我带新图", user_id=22, created_at=2),
            LlmChatTurn(role="user", content="八点在群里喊", user_id=11, created_at=3),
        ]

    async def fake_complete(*_args, **_kwargs):
        return {"content": "以后回复群友时先喊大哥"}

    async def fake_save(*_args, **_kwargs):
        saved["count"] += 1
        return True

    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.make_message_repository", lambda: message_repo(fake_list)
    )
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.complete_chat_message", fake_complete)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)
    cfg = LlmConfig(llm_memory_auto_episode_enabled=True, llm_memory_auto_episode_summary_enabled=True)

    assert await maybe_auto_save_group_episode(bot_id=1, group_id=2, cfg=cfg) is False
    assert saved["count"] == 0


def test_file_ingest_loads_markdown(tmp_path) -> None:
    reset_file_knowledge_registration_for_tests()
    (tmp_path / "sample.md").write_text(
        "# Demo\n\n## 什么是 Pallas\n\nPallas-Bot 是群聊机器人。\n",
        encoding="utf-8",
    )
    decl = load_file_knowledge_decl(root=tmp_path)
    assert decl is not None
    assert decl.source_id == "pallas.file_ingest"
    assert decl.chunks
    titles = {c.title for c in decl.chunks}
    assert "什么是 Pallas" in titles


def test_file_ingest_loads_jsonl_valid_records_only(tmp_path) -> None:
    reset_file_knowledge_registration_for_tests()
    jsonl_path = tmp_path / "sample.jsonl"
    valid_record = {
        "title": "有效 JSONL 记录",
        "content": "这是一段足够长的内容，用于测试 JSONL 文件导入行为。",
        "keywords": "jsonl,ingest",
    }
    too_short_record = {
        "title": "内容太短的记录",
        "content": "短",
        "keywords": "short",
    }
    jsonl_lines = [
        json.dumps(valid_record, ensure_ascii=False),
        json.dumps(too_short_record, ensure_ascii=False),
        json.dumps("not a dict", ensure_ascii=False),
        '{"title": "invalid json"',
    ]
    jsonl_path.write_text("\n".join(jsonl_lines), encoding="utf-8")

    decl = load_file_knowledge_decl(root=tmp_path)
    assert decl is not None
    assert decl.source_id == "pallas.file_ingest"
    titles = {c.title for c in decl.chunks}
    assert titles == {"有效 JSONL 记录"}


def test_file_ingest_ignores_readme_and_dotfiles(tmp_path) -> None:
    reset_file_knowledge_registration_for_tests()
    (tmp_path / "README.md").write_text(
        "# README\n\n## README 标题\n\n这是一段 README 内容。\n",
        encoding="utf-8",
    )
    (tmp_path / ".hidden.md").write_text(
        "# Hidden\n\n## 隐藏标题\n\n这是一段隐藏文件内容。\n",
        encoding="utf-8",
    )
    (tmp_path / "sample.md").write_text(
        "# Demo\n\n## 可见标题\n\n这是一段正常的内容。\n",
        encoding="utf-8",
    )

    decl = load_file_knowledge_decl(root=tmp_path)
    assert decl is not None
    titles = {c.title for c in decl.chunks}
    assert "可见标题" in titles
    assert "README 标题" not in titles
    assert "隐藏标题" not in titles


def test_file_ingest_disabled_via_flag() -> None:
    reset_file_knowledge_registration_for_tests()
    cfg = LlmConfig(llm_knowledge_file_ingest_enabled=False)
    assert ensure_file_knowledge_registered(cfg=cfg) is False


@pytest.mark.asyncio
async def test_auto_episode_skips_bot_identity_or_future_behavior_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    called = {"n": 0}

    async def fake_save(*_args, **_kwargs):
        called["n"] += 1
        return True

    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)
    cfg = LlmConfig(llm_memory_auto_episode_enabled=True, llm_memory_auto_episode_cooldown_sec=0)

    assert await maybe_auto_save_episode(bot_id=1, group_id=2, user_text="以后群友@你先说脏话", cfg=cfg) is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_save_memory_entry_rejects_future_behavior_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.memory.store import save_memory_entry

    monkeypatch.setattr("pallas.product.llm.memory.store.is_llm_memory_store_available", lambda: True)
    assert await save_memory_entry(1, 2, "以后群友@你先说脏话", source="auto_episode") is False


@pytest.mark.asyncio
async def test_auto_episode_skips_noise_fragments(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    called = {"n": 0}

    async def fake_save(*_a, **_k):
        called["n"] += 1
        return True

    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)
    cfg = LlmConfig(llm_memory_auto_episode_enabled=True, llm_memory_auto_episode_cooldown_sec=0)

    for noise in ("阿根廷还是英格兰", "为人民服务不辛苦", "傻逼牛牛我真要制裁你了", "哈哈", "好的收到"):
        assert await maybe_auto_save_episode(bot_id=1, group_id=2, user_text=noise, cfg=cfg) is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_auto_episode_respects_daily_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auto_episode_cooldown_for_tests()
    saved = {"n": 0}

    async def fake_list(*_args, **_kwargs):
        return [
            LlmChatTurn(role="user", content="周五晚上一起开黑吗", user_id=11, created_at=1),
            LlmChatTurn(role="user", content="可以，我带新图", user_id=22, created_at=2),
            LlmChatTurn(role="user", content="八点在群里喊", user_id=11, created_at=3),
        ]

    async def fake_complete(*_args, **_kwargs):
        return {"content": "群友约定周五晚上八点开黑"}

    async def fake_save(*_args, **_kwargs):
        saved["n"] += 1
        return True

    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.make_message_repository", lambda: message_repo(fake_list)
    )
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.complete_chat_message", fake_complete)
    monkeypatch.setattr("pallas.product.llm.memory.auto_episode.save_memory_entry", fake_save)

    cfg = LlmConfig(
        llm_memory_auto_episode_enabled=True,
        llm_memory_auto_episode_summary_enabled=True,
        llm_memory_auto_episode_cooldown_sec=0,
        llm_memory_auto_episode_daily_budget=1,
    )
    assert await maybe_auto_save_group_episode(bot_id=1, group_id=2, cfg=cfg) is True
    assert await maybe_auto_save_group_episode(bot_id=1, group_id=2, cfg=cfg) is False
    assert saved["n"] == 1
