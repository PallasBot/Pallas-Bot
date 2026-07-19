from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.kernel.memory_governance import can_read_generic_knowledge
from pallas.product.llm.knowledge import builtin as knowledge_builtin  # noqa: F401
from pallas.product.llm.knowledge.builtin.bot_faq import BOT_FAQ_SOURCE
from pallas.product.llm.knowledge.declare import knowledge_source_row
from pallas.product.llm.knowledge.inject import enrich_system_with_knowledge_sources
from pallas.product.llm.knowledge.metadata import parse_knowledge_source_decl
from pallas.product.llm.knowledge.registry import (
    knowledge_metadata_payload,
    list_active_knowledge_sources,
    retrieve_from_knowledge_sources,
)
from pallas.product.llm.knowledge.retrieve import retrieve_chunks_from_decl


def test_parse_knowledge_source_decl_accepts_plugin_row() -> None:
    raw = knowledge_source_row(
        source_id="demo.faq",
        title="演示 FAQ",
        chunks=[{"title": "帮助", "content": "这是帮助内容", "keywords": "帮助"}],
    )
    decl = parse_knowledge_source_decl(raw)
    assert decl is not None
    assert decl.source_id == "demo.faq"
    assert decl.chunks[0].content == "这是帮助内容"


def test_builtin_bot_faq_retrieves_on_clear_keyword() -> None:
    hits = retrieve_chunks_from_decl(BOT_FAQ_SOURCE, "怎么清空会话", top_k=3, max_chunk_len=400)
    assert hits
    assert any("clear" in item.content.lower() or "清空" in item.content for item in hits)


@pytest.mark.asyncio
async def test_enrich_system_with_knowledge_sources_injects_block() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=True)
    result = await enrich_system_with_knowledge_sources(
        "你是牛牛。",
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="怎么清空聊天记录",
        cfg=cfg,
    )
    assert "相关知识参考" in result.system_prompt
    assert result.trace["hit_count"] >= 1
    assert "pallas.bot_faq" in result.trace["sources"]


def test_can_read_generic_knowledge_respects_config() -> None:
    enabled = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=True)
    disabled = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=False)
    assert can_read_generic_knowledge(enabled) is True
    assert can_read_generic_knowledge(disabled) is False


def test_list_active_knowledge_sources_includes_builtin() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=True)
    rows = list_active_knowledge_sources(cfg=cfg)
    assert any(row.source_id == "pallas.bot_faq" for row in rows)


def test_knowledge_metadata_payload_includes_trace() -> None:
    trace = {"hit_count": 1, "sources": ["pallas.bot_faq"], "chunks": []}
    payload = knowledge_metadata_payload(trace, cfg=LlmConfig(llm_chat_enabled=True))
    assert payload["knowledge_contract_version"] == 1
    assert payload["retrieval_trace"]["hit_count"] == 1
    assert payload["knowledge_policy"]["allow_generic_knowledge"] is True


def test_retrieve_from_knowledge_sources_returns_sorted_hits() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=True)
    hits = retrieve_from_knowledge_sources("清空 clear", bot_id=1, group_id=2, user_id=3, cfg=cfg)
    assert hits
    assert hits[0].source_id in {"pallas.bot_faq", "llm_chat.faq"}


def test_llm_chat_plugin_declares_knowledge_source() -> None:
    from packages.llm_chat import __plugin_meta__
    from pallas.product.llm.knowledge.metadata import knowledge_sources_from_metadata

    decls = knowledge_sources_from_metadata(__plugin_meta__)
    assert any(decl.source_id == "llm_chat.faq" for decl in decls)
    faq = next(decl for decl in decls if decl.source_id == "llm_chat.faq")
    assert len(faq.chunks) >= 2


@pytest.mark.parametrize(
    ("module_path", "source_id"),
    [
        ("packages.help", "help.faq"),
        ("packages.drink", "drink.faq"),
        ("packages.greeting", "greeting.faq"),
        ("packages.roulette", "roulette.faq"),
        ("packages.take_name", "take_name.faq"),
    ],
)
def test_core_plugins_declare_knowledge_sources(module_path: str, source_id: str) -> None:
    import importlib

    from pallas.product.llm.knowledge.metadata import knowledge_sources_from_metadata

    mod = importlib.import_module(module_path)
    decls = knowledge_sources_from_metadata(mod.__plugin_meta__)
    assert any(decl.source_id == source_id for decl in decls)
    faq = next(decl for decl in decls if decl.source_id == source_id)
    assert len(faq.chunks) >= 2


def load_plugin_meta_from_init(init_path: Path, *, cut_before: str):
    spec = importlib.util.spec_from_file_location(f"meta_probe_{init_path.stem}", init_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    code = init_path.read_text(encoding="utf-8")
    if cut_before in code:
        code = code.split(cut_before, 1)[0]
    code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("from ."))
    exec(compile(code, str(init_path), "exec"), module.__dict__)  # noqa: S102
    return module.__plugin_meta__


@pytest.mark.parametrize(
    ("rel_path", "source_id", "cut_before"),
    [
        (
            "../Pallas-Plugin-Draw/src/pallas_plugin_draw/__init__.py",
            "draw.faq",
            "from . import draw as _pallas_draw",
        ),
        (
            "../pallas-community-plugin-interact/__init__.py",
            "interact.faq",
            "praise_cmd = message_command",
        ),
    ],
)
def test_extension_plugins_declare_knowledge_sources(rel_path: str, source_id: str, cut_before: str) -> None:
    from pallas.product.llm.knowledge.metadata import knowledge_sources_from_metadata

    init_path = (Path(__file__).resolve().parents[2] / rel_path).resolve()
    if not init_path.is_file():
        pytest.skip(f"missing extension metadata file: {init_path}")
    meta = load_plugin_meta_from_init(init_path, cut_before=cut_before)
    decls = knowledge_sources_from_metadata(meta)
    assert any(decl.source_id == source_id for decl in decls)
    faq = next(decl for decl in decls if decl.source_id == source_id)
    assert len(faq.chunks) >= 2


@pytest.mark.asyncio
async def test_enrich_skips_when_generic_knowledge_disabled() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=False)
    result = await enrich_system_with_knowledge_sources(
        "你是牛牛。",
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="怎么清空",
        cfg=cfg,
    )
    assert result.system_prompt == "你是牛牛。"
    assert result.trace["hit_count"] == 0
