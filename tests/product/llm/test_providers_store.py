"""Bot 侧 llm providers 事实源。"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.providers_store import (
    bot_providers_configured,
    clear_providers_store_cache,
    export_providers_for_api,
    load_providers_document,
    resolve_endpoint_for_task,
    save_providers_document,
)
from pallas.product.llm.submit_gate import assess_llm_kernel_submit_gate


def test_providers_store_roundtrip(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    clear_llm_config_cache()

    saved = save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-test-key",
                "default_model": "deepseek-v4-flash",
                "task_models": {"llm_chat": "deepseek-v4-flash"},
                "model_pricing": {"deepseek-v4-flash": {"price_in": 0.5, "price_out": 1.2}},
            }
        ],
        "routing": {"chain_fallback": ["ds"], "tasks": {"llm_chat": "ds"}, "cost_currency": "cny"},
    })
    assert saved["file_exists"] is True
    assert saved["providers"][0]["api_key_set"] is True
    assert saved["providers"][0]["api_keys"] == []
    assert saved["providers"][0]["api_key"] == ""
    assert saved["providers"][0]["api_key_hints"] == ["sk-tes*****key"]
    assert saved["providers"][0]["api_keys_count"] == 1
    assert saved["providers"][0]["model_pricing"]["deepseek-v4-flash"]["price_in"] == 0.5
    assert saved["routing"]["cost_currency"] == "CNY"

    clear_providers_store_cache()
    endpoint = resolve_endpoint_for_task("llm_chat")
    assert endpoint is not None
    assert endpoint.provider_id == "ds"
    assert endpoint.base_url == "https://api.deepseek.com"
    assert endpoint.api_key == "sk-test-key"
    assert endpoint.model == "deepseek-v4-flash"
    assert bot_providers_configured() is True

    gate = assess_llm_kernel_submit_gate(LlmConfig(llm_base_url="", llm_model=""))
    assert gate.allowed is True

    exported = export_providers_for_api()
    assert exported["providers"][0]["id"] == "ds"
    assert exported["providers"][0]["api_key_set"] is True
    assert exported["providers"][0]["api_keys"] == []
    assert exported["providers"][0]["api_key_hints"] == ["sk-tes*****key"]
    raw = json.loads(store.read_text(encoding="utf-8"))
    assert raw["providers"][0]["api_key"] == "sk-test-key"


def test_providers_store_migrates_legacy_pricing_to_registered_models(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    saved = save_providers_document({
        "providers": [
            {
                "id": "ds",
                "base_url": "https://api.deepseek.com",
                "default_model": "deepseek-chat",
                "task_models": {"llm_chat": "deepseek-reasoner"},
                "model_pricing": {"deepseek-reasoner": {"price_in": 1, "price_out": 2}},
            }
        ],
        "routing": {},
    })
    models = saved["providers"][0]["models"]
    assert [model["name"] for model in models] == ["deepseek-chat", "deepseek-reasoner"]
    assert models[1]["pricing_rules"][0]["kind"] == "token"


def test_endpoint_uses_registered_model_capabilities_and_effort(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "gateway",
                "base_url": "https://example.test/v1",
                "default_model": "vision-model",
                "task_models": {"llm_chat": "vision-model"},
                "capabilities": ["text"],
                "model_effort": "low",
                "models": [
                    {"name": "vision-model", "capabilities": ["text", "image"], "model_effort": "medium"},
                    {"name": "plain-model", "capabilities": ["text"], "model_effort": "disable"},
                ],
            }
        ],
        "routing": {"tasks": {"llm_chat": "gateway"}},
    })

    endpoint = resolve_endpoint_for_task("llm_chat")

    assert endpoint is not None
    assert endpoint.capabilities == ("text", "image")
    assert endpoint.model_effort == "medium"


def test_endpoint_falls_back_to_provider_capabilities_and_effort(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "gateway",
                "base_url": "https://example.test/v1",
                "default_model": "plain-model",
                "capabilities": ["text", "image"],
                "model_effort": "high",
                "models": [{"name": "plain-model"}],
            }
        ],
        "routing": {"tasks": {"llm_chat": "gateway"}},
    })

    endpoint = resolve_endpoint_for_task("llm_chat")

    assert endpoint is not None
    assert endpoint.capabilities == ("text", "image")
    assert endpoint.model_effort == "high"


def test_providers_store_preserves_api_key_on_blank_update(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-keep",
                "default_model": "m1",
            }
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com",
                "api_key": "",
                "default_model": "m2",
            }
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    clear_providers_store_cache()
    doc = load_providers_document()
    assert doc["providers"][0]["api_key"] == "sk-keep"
    assert doc["providers"][0]["default_model"] == "m2"


def test_providers_store_upsert_does_not_touch_other_secrets(tmp_path: Path, monkeypatch) -> None:
    from pallas.product.llm.providers_store import upsert_provider_row

    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-ds-keep",
                "default_model": "deepseek-v4-flash",
            },
            {
                "id": "AK",
                "kind": "remote",
                "base_url": "https://aigateway.akile.ai",
                "api_key": "sk-ak-keep",
                "default_model": "gpt-x",
            },
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    clear_providers_store_cache()
    upsert_provider_row({
        "id": "AK",
        "kind": "remote",
        "base_url": "https://aigateway.akile.ai",
        "api_key": "sk-ak-new",
        "default_model": "gpt-y",
    })
    clear_providers_store_cache()
    doc = load_providers_document()
    by_id = {row["id"]: row for row in doc["providers"]}
    assert by_id["ds"]["api_key"] == "sk-ds-keep"
    assert by_id["AK"]["api_key"] == "sk-ak-new"
    assert by_id["AK"]["default_model"] == "gpt-y"


def test_providers_store_multi_api_keys_and_capabilities(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    saved = save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com/v1",
                "api_keys": ["sk-first", "sk-second"],
                "default_model": "m1",
                "capabilities": ["text", "image", "unknown"],
                "model_effort": "high",
            }
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    assert saved["providers"][0]["api_keys_count"] == 2
    assert saved["providers"][0]["api_keys"] == []
    assert saved["providers"][0]["api_key_hints"] == ["****", "****"]
    assert saved["providers"][0]["capabilities"] == ["text", "image"]
    assert saved["providers"][0]["model_effort"] == "high"
    clear_providers_store_cache()
    endpoint = resolve_endpoint_for_task("llm_chat")
    assert endpoint is not None
    assert endpoint.api_key == "sk-first"
    assert endpoint.api_keys == ("sk-first", "sk-second")
    assert endpoint.capabilities == ("text", "image")
    assert endpoint.model_effort == "high"
    raw = json.loads(store.read_text(encoding="utf-8"))
    assert raw["providers"][0]["api_keys"] == ["sk-first", "sk-second"]
    assert raw["providers"][0]["api_key"] == "sk-first"

    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "",
                "default_model": "m2",
                "capabilities": ["text", "audio"],
            }
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    clear_providers_store_cache()
    doc = load_providers_document()
    assert doc["providers"][0]["api_keys"] == ["sk-first", "sk-second"]
    assert doc["providers"][0]["capabilities"] == ["text", "audio"]

    # 空 api_keys 且无 clear 标志：保留密钥（模拟 WebUI PUT 默认注入）
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "",
                "api_keys": [],
                "default_model": "m2b",
            }
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    clear_providers_store_cache()
    kept = load_providers_document()
    assert kept["providers"][0]["api_keys"] == ["sk-first", "sk-second"]
    assert kept["providers"][0]["default_model"] == "m2b"

    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.deepseek.com/v1",
                "api_keys": [],
                "clear_api_keys": True,
                "default_model": "m3",
            }
        ],
        "routing": {"tasks": {"llm_chat": "ds"}},
    })
    clear_providers_store_cache()
    cleared = load_providers_document()
    assert cleared["providers"][0]["api_keys"] == []
    assert cleared["providers"][0]["api_key"] == ""
    assert cleared["providers"][0]["default_model"] == "m3"


def test_providers_store_anthropic_request_method(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "claude",
                "kind": "remote",
                "base_url": "https://api.anthropic.com",
                "api_key": "sk-ant-x",
                "default_model": "claude-sonnet-4-5",
                "request_method": "anthropic_messages",
            }
        ],
        "routing": {"tasks": {"llm_chat": "claude"}},
    })
    clear_providers_store_cache()
    endpoint = resolve_endpoint_for_task("llm_chat")
    assert endpoint is not None
    assert endpoint.request_method == "anthropic_messages"
    exported = export_providers_for_api()
    assert exported["providers"][0]["request_method"] == "anthropic_messages"


def test_resolve_endpoint_candidates_follow_chain_fallback(tmp_path: Path, monkeypatch) -> None:
    from pallas.product.llm.providers_store import resolve_endpoint_candidates_for_task

    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "a",
                "kind": "remote",
                "base_url": "https://a.example/v1",
                "api_key": "sk-a",
                "default_model": "ma",
            },
            {
                "id": "b",
                "kind": "remote",
                "base_url": "https://b.example/v1",
                "api_key": "sk-b",
                "default_model": "mb",
            },
        ],
        "routing": {"chain_fallback": ["a", "b"], "tasks": {"llm_chat": "a"}},
    })
    clear_providers_store_cache()
    candidates = resolve_endpoint_candidates_for_task("llm_chat")
    assert [item.provider_id for item in candidates] == ["a", "b"]
    assert candidates[1].model == "mb"


def test_providers_store_reloads_when_disk_revision_changes(tmp_path: Path, monkeypatch) -> None:
    """模拟 hub 写盘、worker 进程内缓存：不显式 clear 也应按 mtime 热载。"""
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "packy",
                "kind": "remote",
                "base_url": "https://packy.example/v1",
                "api_key": "sk-packy",
                "default_model": "m-packy",
            }
        ],
        "routing": {"chain_fallback": ["packy"], "tasks": {"llm_chat": "packy"}},
    })
    first = resolve_endpoint_for_task("llm_chat")
    assert first is not None
    assert first.provider_id == "packy"

    # 另一进程（hub）直接改文件，本进程不走 save_providers_document
    payload = json.loads(store.read_text(encoding="utf-8"))
    payload["providers"] = [
        {
            "id": "ds",
            "kind": "remote",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-ds",
            "default_model": "deepseek-chat",
            "enabled": True,
            "task_models": {},
            "capabilities": [],
            "model_effort": "",
            "request_method": "chat_completions",
            "model_pricing": {},
        }
    ]
    payload["routing"]["tasks"] = {"llm_chat": "ds"}
    payload["routing"]["chain_fallback"] = ["ds"]
    store.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    second = resolve_endpoint_for_task("llm_chat")
    assert second is not None
    assert second.provider_id == "ds"
    assert second.base_url == "https://api.deepseek.com"
