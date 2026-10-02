from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.assembler.chat_prompt import ChatPromptAssembler
from pallas.product.llm.assembler.context import assemble_direct_chat_context
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.models import KnowledgeInjectionResult
from pallas.product.llm.memory.inject import (
    MemoryInjectionResult,
    PersonFactsInjectionResult,
    RelationshipInjectionResult,
)
from pallas.product.llm.reply_shape import ReplyShapePolicy
from pallas.product.llm.turn_policy import TurnPolicy


def test_assembler_package_omits_retired_repeater_context() -> None:
    import pallas.product.llm.assembler as assembler

    assert not hasattr(assembler, "assemble_repeater_context")


@pytest.mark.asyncio
async def test_direct_chat_context_returns_retrieval_blocks_without_expression_append(monkeypatch) -> None:
    memory = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_memory_context", memory)
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_knowledge_sources", knowledge)
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_relationship_context",
        AsyncMock(return_value=RelationshipInjectionResult(system_prompt="", trace={"hit_count": 0})),
    )
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_person_facts",
        AsyncMock(return_value=PersonFactsInjectionResult(system_prompt="", trace={"hit_count": 0})),
    )
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="牛牛出来",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
    )

    assert result.memory == "memory"
    assert result.knowledge == "knowledge"
    assert result.relationship == ""
    assert result.person_facts == ""
    assert "expression" not in result.stage_durations_ms


@pytest.mark.asyncio
async def test_direct_chat_context_keeps_retrieval_blocks_separate(monkeypatch) -> None:
    memory = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_memory_context", memory)
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_knowledge_sources", knowledge)
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_relationship_context",
        AsyncMock(return_value=RelationshipInjectionResult(system_prompt="", trace={"hit_count": 0})),
    )
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_person_facts",
        AsyncMock(return_value=PersonFactsInjectionResult(system_prompt="", trace={"hit_count": 0})),
    )
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="牛牛出来",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
    )

    assert result.memory == "memory"
    assert result.knowledge == "knowledge"
    assert "expression" not in result.stage_durations_ms


@pytest.mark.asyncio
async def test_scoped_context_reaches_provider_without_other_group_or_bot_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from pallas.product.llm import provider_client
    from pallas.product.llm.knowledge import registry as knowledge_registry
    from pallas.product.llm.knowledge.models import (
        KnowledgeChunkDecl,
        KnowledgeSourceDecl,
        KnowledgeSourceScope,
    )
    from pallas.product.llm.memory import consent, person_facts, store
    from pallas.product.llm.tool_loop import complete_with_tool_loop

    rows = [
        SimpleNamespace(
            id=index,
            bot_id=bot_id,
            group_id=group_id,
            content=content,
            keywords="星轨,项目",
            source="teach",
            importance=0.9,
            confidence=0.9,
            expires_at=0,
            visibility="group",
            created_at=1,
            updated_at=1,
            embedding_json=None,
            embedding_model=None,
        )
        for index, bot_id, group_id, content in (
            (1, 1, 42, "当前群的星轨项目记忆"),
            (2, 1, 41, "其他群的星轨项目哨兵"),
            (3, 2, 42, "其他机器人的星轨项目哨兵"),
        )
    ]

    class QueryResult:
        def scalars(self):
            return self

        def all(self):
            return rows

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, _statement):
            return QueryResult()

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(store, "is_llm_memory_store_available", lambda: True)
    monkeypatch.setattr(store, "_use_mongodb_backend", lambda: False)
    monkeypatch.setattr(store, "_use_postgresql_backend", lambda: True)
    monkeypatch.setattr(store, "get_session", lambda **_kwargs: Session())
    monkeypatch.setattr(store, "touch_memory_hit_timestamps", noop)
    monkeypatch.setattr("pallas.product.llm.memory.retrieve.vector_retrieve_mode", lambda _cfg=None: "keyword")
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg=None: "keyword")

    monkeypatch.setattr(person_facts, "_store_path", lambda: tmp_path / "person_facts.json")
    monkeypatch.setattr(consent, "_store_path", lambda: tmp_path / "person_consent.json")
    person_facts.save_person_fact(bot_id=1, group_id=41, user_id=7, content="其他群人物事实哨兵")
    person_facts.save_person_fact(bot_id=1, group_id=42, user_id=7, content="当前群人物事实")
    consent.set_consent(7, platform="qq", granted=True, scopes=["stable_preferences"])
    person_facts.save_person_fact(
        bot_id=1,
        group_id=42,
        user_id=7,
        content="同意跨群复用的人物事实",
        scope="global",
    )

    current_bot_source = KnowledgeSourceDecl(
        source_id="test.current_bot",
        title="当前 bot 知识",
        scope=KnowledgeSourceScope.BOT,
        bot_id=1,
        chunks=[KnowledgeChunkDecl(title="星轨项目", content="当前 bot 的星轨项目知识", keywords="星轨,项目")],
    )
    other_bot_source = KnowledgeSourceDecl(
        source_id="test.other_bot",
        title="其他 bot 知识",
        scope=KnowledgeSourceScope.BOT,
        bot_id=2,
        chunks=[KnowledgeChunkDecl(title="星轨项目", content="其他 bot 知识哨兵", keywords="星轨,项目")],
    )
    monkeypatch.setattr(
        knowledge_registry,
        "iter_loaded_plugin_knowledge_sources",
        lambda: [
            ("test", "test", current_bot_source),
            ("test", "test", other_bot_source),
        ],
    )
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.file_ingest.ensure_file_knowledge_registered",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(knowledge_registry, "_BUILTIN_SOURCES", [])

    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_memory_rag_enabled=True,
        llm_knowledge_sources_enabled=True,
        llm_knowledge_file_ingest_enabled=False,
        llm_knowledge_min_score=1,
        llm_vector_retrieve="keyword",
        llm_embedding_model="stub",
        llm_base_url="http://provider.invalid/v1",
        llm_model="test-model",
        llm_tools_enabled=False,
    )
    captured: list[dict] = []

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "choices": [{"message": {"role": "assistant", "content": "收到"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    class HttpClient:
        async def post(self, _url, *, json, **_kwargs):
            captured.append(json)
            return Response()

    async def get_client():
        return HttpClient()

    monkeypatch.setattr(provider_client, "get_llm_shared_httpx_client", get_client)
    monkeypatch.setattr("pallas.product.llm.providers_store.resolve_endpoint_candidates_for_task", lambda _task: [])
    monkeypatch.setattr("pallas.product.llm.providers_store.resolve_endpoint_for_task", lambda _task: None)

    context = await assemble_direct_chat_context(
        bot_id=1,
        group_id=42,
        user_id=7,
        query_text="之前提到的星轨项目怎么查？",
        cfg=cfg,
        group_timeline="【当前群时间线哨兵】",
    )
    system_prompt = ChatPromptAssembler().assemble(
        core_persona="核心人设",
        self_identity="",
        turn_policy=TurnPolicy("fact", "serious", "ANSWER", False, False, False, True),
        context=context,
        group_expression=None,
        reply_shape=ReplyShapePolicy(1, 2, 1, 40, "complete", "single", 128),
    )
    content, _assistant = await complete_with_tool_loop(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": "之前提到的星轨项目怎么查？"}],
        metadata={"task": "llm_chat", "resolved_model": "test-model"},
        cfg=cfg,
    )

    provider_system = next(item["content"] for item in captured[0]["messages"] if item["role"] == "system")
    assert content == "收到"
    assert "当前群的星轨项目记忆" in provider_system
    assert "当前群人物事实" in provider_system
    assert "同意跨群复用的人物事实" in provider_system
    assert "当前 bot 的星轨项目知识" in provider_system
    assert "其他群的星轨项目哨兵" not in provider_system
    assert "其他机器人的星轨项目哨兵" not in provider_system
    assert "其他群人物事实哨兵" not in provider_system
    assert "其他 bot 知识哨兵" not in provider_system
    assert "【当前群时间线哨兵】" in provider_system


@pytest.mark.asyncio
async def test_short_social_turn_skips_persistent_personal_retrieval_but_keeps_timeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from pallas.product.llm.memory import consent, person_facts
    from pallas.product.llm.memory.relationship_store import RelationshipProfile

    monkeypatch.setattr(person_facts, "_store_path", lambda: tmp_path / "person_facts.json")
    monkeypatch.setattr(consent, "_store_path", lambda: tmp_path / "person_consent.json")
    person_facts.save_person_fact(bot_id=1, group_id=42, user_id=7, content="短回合不该出现的人物事实")

    async def relationship_profile(*_args, **_kwargs):
        return RelationshipProfile(content="短回合不该出现的关系事实")

    async def old_topic(*_args, **_kwargs):
        return [{"summary": "短回合不该出现的旧话题"}]

    relationship_retrieval = AsyncMock(side_effect=relationship_profile)
    monkeypatch.setattr("pallas.product.llm.memory.inject.retrieve_relationship_profile", relationship_retrieval)
    monkeypatch.setattr("pallas.product.llm.memory.mid_term.recall_related_mid_term_summaries", old_topic)
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "keyword")
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_knowledge_sources",
        AsyncMock(
            return_value=KnowledgeInjectionResult(system_prompt="", trace={"hit_count": 0}),
        ),
    )

    context = await assemble_direct_chat_context(
        bot_id=1,
        group_id=42,
        user_id=7,
        query_text="今天怎么样",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
        group_timeline="【允许保留的群时间线】",
    )
    prompt = ChatPromptAssembler().assemble(
        core_persona="核心人设",
        self_identity="",
        turn_policy=TurnPolicy("emotion", "light", "ACK", True, True, False, False),
        context=context,
        group_expression=None,
        reply_shape=ReplyShapePolicy(1, 1, 1, 20, "short", "single", 64),
    )

    assert "短回合不该出现的人物事实" not in prompt
    assert "短回合不该出现的关系事实" not in prompt
    assert "短回合不该出现的旧话题" not in prompt
    assert "【允许保留的群时间线】" in prompt
    relationship_retrieval.assert_not_awaited()
