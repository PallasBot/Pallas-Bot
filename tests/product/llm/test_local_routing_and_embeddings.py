from __future__ import annotations

from pallas.product.llm.knowledge.embedding_client import fetch_embeddings_sync, stub_embedding
from pallas.product.llm.local_routing_store import (
    clear_local_routing_cache,
    export_local_routing_for_api,
    resolve_local_task_model,
    save_local_routing_document,
)


def test_stub_embedding_deterministic() -> None:
    a = stub_embedding("hello")
    b = stub_embedding("hello")
    c = stub_embedding("world")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_fetch_embeddings_sync_local() -> None:
    vectors = fetch_embeddings_sync(["a", "b"])
    assert vectors is not None
    assert len(vectors) == 2


def test_local_routing_store_roundtrip(tmp_path, monkeypatch) -> None:
    path = tmp_path / "llm_local_routing.json"
    monkeypatch.setattr("pallas.product.llm.local_routing_store.local_routing_store_path", lambda: path)
    clear_local_routing_cache()
    saved = save_local_routing_document({
        "llm_model": "qwen3:8b",
        "local_multi_model_enabled": True,
        "task_models": {"llm_chat": "qwen3:14b", "drunk": "qwen2.5:0.5b"},
        "moe_models": {"simple": "s", "medium": "m", "complex": "c", "vision": "v"},
    })
    assert saved["llm_model"] == "qwen3:8b"
    assert saved["task_models"]["llm_chat"] == "qwen3:14b"
    clear_local_routing_cache()
    exported = export_local_routing_for_api()
    assert exported["local_multi_model_enabled"] is True
    assert (
        not {
            "repeater_select",
            "repeater_polish",
            "repeater_polish_lite",
            "repeater_fallback",
        }
        & exported["task_models"].keys()
    )
    assert resolve_local_task_model("llm_chat") == "qwen3:14b"
