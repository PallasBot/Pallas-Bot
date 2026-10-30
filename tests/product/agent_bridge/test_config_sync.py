from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit

from pallas.product.agent_bridge import config_sync
from pallas.product.agent_bridge.config_sync import (
    BOT_CONFIG_FILENAME,
    MODEL_CONFIG_FILENAME,
    ConfigSyncError,
    config_sync_enabled,
    config_sync_preflight,
    sync_maibot_config,
)
from pallas.product.llm.providers_store import ResolvedLlmEndpoint

CHAT_KEY_A = "sk-chat-key-a"
CHAT_KEY_B = "sk-chat-key-b"
CHAT_KEY_C = "sk-chat-key-c"
EMBED_KEY_A = "sk-embed-key-a"
URL_A = "https://alpha.example.invalid/v1"
URL_B = "https://beta.example.invalid/v1"

BOT_CONFIG = """[inner]
version = "8.15.47"

[bot]
nickname = "Mai"
alias_names = ["old alias"]

[personality]
personality = "native persona"
"""

MODEL_CONFIG = """[inner]
version = "1.17.24"

[[api_providers]]
name = "manual-provider"
base_url = "https://manual.example.invalid/v1"
api_key = "manual-key"
client_type = "openai"
auth_type = "bearer"
max_retry = 4
timeout = 22

[[models]]
name = "manual-model"
model_identifier = "manual-model"
model_type = "llm"
api_provider = "manual-provider"

[[models]]
name = "manual-embedding"
model_identifier = "manual-embedding"
model_type = "embedding"
api_provider = "manual-provider"

[model_task_config.replyer]
model_list = []

[model_task_config.planner]
model_list = []

[model_task_config.utils]
model_list = []

[model_task_config.memory]
model_list = ["manual-model"]

[model_task_config.embedding]
model_list = ["manual-embedding"]
"""

_DEFAULT_CORE_TASK_MODELS = {
    "replyer": ["deepseek-v4-pro-think", "deepseek-v4-pro-nonthink"],
    "planner": ["deepseek-v4-flash"],
    "utils": ["deepseek-v4-flash"],
}
_EXPECTED_NATIVE_TASKS = {
    "replyer",
    "planner",
    "memory",
    "utils",
    "learner",
    "fast_model",
    "emoji",
    "vlm",
    "voice",
    "embedding",
    "image_embedding",
}
_NATIVE_PROJECT = Path("/tmp/opencode/maibot-provider-proof/native-project")
_NATIVE_SOURCE = _NATIVE_PROJECT / "source"
_NATIVE_PYTHON = _NATIVE_PROJECT / "venv" / "bin" / "python"
_DEFAULT_NATIVE_TEMPLATE = Path(
    "/tmp/opencode/maibot-parent-activation-20261030/runs/"
    "integrated-20261030-102655-fd462f62/instance/config/model_config.toml"
)


def _instance(tmp_path: Path, model_config: str = MODEL_CONFIG) -> Path:
    instance = tmp_path / "instance"
    config = instance / "config"
    config.mkdir(parents=True)
    (config / BOT_CONFIG_FILENAME).write_text(BOT_CONFIG, encoding="utf-8")
    (config / MODEL_CONFIG_FILENAME).write_text(model_config, encoding="utf-8")
    return instance


def _provider(
    provider_id: str,
    *,
    base_url: str = URL_A,
    api_keys: list[str] | None = None,
    models: list[dict] | None = None,
    request_method: str = "chat_completions",
    enabled: bool = True,
    **extra,
) -> dict:
    rows = models or [{"name": "chat-a", "capabilities": ["text", "image"], "model_effort": "low"}]
    return {
        "id": provider_id,
        "kind": "remote",
        "base_url": base_url,
        "api_key": (api_keys or [""])[0],
        "api_keys": list(api_keys or []),
        "api_key_env": "",
        "default_model": rows[0]["name"],
        "models": rows,
        "enabled": enabled,
        "task_models": {},
        "capabilities": ["text"],
        "model_effort": "",
        "request_method": request_method,
        "model_pricing": {},
        "daily_tokens_cap": 0,
        "daily_cost_cap": 0.0,
        **extra,
    }


def _endpoint(provider_id: str, model: str, base_url: str, keys: tuple[str, ...]) -> ResolvedLlmEndpoint:
    return ResolvedLlmEndpoint(
        provider_id=provider_id,
        base_url=base_url,
        api_key=keys[0] if keys else "",
        api_keys=keys,
        model=model,
    )


def _source_document(*, providers: list[dict] | None = None, routes: dict | None = None) -> dict:
    rows = providers or [
        _provider(
            "alpha",
            api_keys=[CHAT_KEY_A, CHAT_KEY_B],
            models=[
                {"name": "chat-a", "capabilities": ["text", "image"], "model_effort": "low"},
                {"name": "chat-unused", "capabilities": ["text"]},
            ],
        ),
        _provider(
            "beta", base_url=URL_B, api_keys=[CHAT_KEY_C], models=[{"name": "chat-b"}], request_method="responses"
        ),
        _provider("disabled", api_keys=["sk-disabled"], enabled=False, models=[{"name": "chat-disabled"}]),
    ]
    task_routes = routes or {"llm_chat": ["alpha", "beta"], "turn_decision": ["alpha"]}
    return {
        "providers": rows,
        "routing": {
            "tasks": {task: ids[0] for task, ids in task_routes.items() if ids},
            "task_backups": {task: ids[1] for task, ids in task_routes.items() if len(ids) > 1},
            "task_backup_models": {},
            "tier_backups": {},
            "tier_backup_models": {},
            "chain_fallback": [],
            "cost_currency": "CNY",
        },
    }


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    document: dict | None = None,
    endpoints: dict[str, list[ResolvedLlmEndpoint]] | None = None,
    config: SimpleNamespace | None = None,
    embedding: dict | None = None,
) -> None:
    source_file = tmp_path / "llm_providers.json"
    source_file.write_text("{}", encoding="utf-8")
    doc = document or _source_document()
    endpoints = endpoints or {
        "llm_chat": [
            _endpoint("alpha", "chat-a", URL_A, (CHAT_KEY_A, CHAT_KEY_B)),
            _endpoint("beta", "chat-b", URL_B, (CHAT_KEY_C,)),
        ],
        "turn_decision": [_endpoint("alpha", "chat-a", URL_A, (CHAT_KEY_A, CHAT_KEY_B))],
    }
    monkeypatch.setattr(config_sync.providers_store, "providers_store_path", lambda: source_file)
    monkeypatch.setattr(config_sync.providers_store, "load_providers_document", lambda **_kwargs: doc)
    monkeypatch.setattr(
        config_sync.providers_store,
        "resolve_endpoint_candidates_for_task",
        lambda task: list(endpoints.get(task, [])),
    )
    monkeypatch.setattr(
        config_sync,
        "get_llm_config",
        lambda: (
            config
            or SimpleNamespace(
                llm_base_url="",
                llm_model="",
                llm_api_key="",
                llm_chat_daily_calls_limit=0,
                llm_chat_daily_tokens_limit=0,
                llm_embedding_provider="stub",
                llm_embedding_base_url="",
                llm_embedding_api_key="",
                llm_embedding_provider_id="",
            )
        ),
    )
    monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: "migrated persona")
    monkeypatch.setattr(config_sync, "extract_generic_self_aliases", lambda: ["牛牛", "麦麦"])
    monkeypatch.setattr(config_sync, "_load_embedding_source", lambda *_args, **_kwargs: embedding)


def _model_doc(instance: Path) -> dict:
    return tomllib.loads((instance / "config" / MODEL_CONFIG_FILENAME).read_text(encoding="utf-8"))


def _rows_by_name(rows: list[dict]) -> dict[str, dict]:
    return {row["name"]: row for row in rows}


def _marker(instance: Path) -> dict:
    return json.loads((instance / "config" / config_sync.MARKER_FILENAME).read_text(encoding="utf-8"))


def _v1_marker() -> dict:
    return {
        "version": 1,
        "bot_config_version": "8.15.47",
        "model_config_version": "1.17.24",
        "digest": "a" * 64,
        "provider_names": ["pallas-alpha"],
        "model_names": ["pallas-alpha-chat"],
        "task_keys": ["replyer", "planner", "utils"],
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _snapshot(instance: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in (instance / "config").iterdir()}


def _fail_source_read(*_args, **_kwargs):
    raise AssertionError("Pallas source read")


def _native_alias_fixture() -> str:
    doc = tomlkit.parse(MODEL_CONFIG)
    provider = tomlkit.table()
    provider.update({
        "name": "pallas-managed",
        "base_url": "http://pallas-provider.invalid",
        "api_key": "",
        "client_type": "pallas-managed",
        "auth_type": "none",
        "max_retry": 1,
        "timeout": 60,
    })
    model_rows = []
    for name, model_type in (("pb-route-chat", "llm"), ("pb-route-decision", "llm")):
        row = tomlkit.table()
        row.update({
            "name": name,
            "model_identifier": name,
            "model_type": model_type,
            "api_provider": "pallas-managed",
            "visual": False,
            "force_stream_mode": False,
            "extra_params": {},
        })
        model_rows.append(row)
    doc["api_providers"].append(provider)
    for row in model_rows:
        doc["models"].append(row)
    for task, model in (("replyer", "pb-route-chat"), ("planner", "pb-route-chat"), ("utils", "pb-route-decision")):
        doc["model_task_config"][task]["model_list"] = [model]
    return tomlkit.dumps(doc)


def _default_native_model_fixture() -> str:
    doc = tomlkit.parse(MODEL_CONFIG)
    provider = doc["api_providers"][0]
    provider.update({
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_key": "your-api-key",
        "client_type": "openai",
        "auth_type": "bearer",
    })
    models = doc["models"]
    del models[:]
    defaults = (
        ("deepseek-v4-pro-think", "deepseek-v4-pro", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
        ("deepseek-v4-pro-nonthink", "deepseek-v4-pro", {"thinking": {"type": "disabled"}}),
        ("deepseek-v4-flash", "deepseek-v4-flash", {"thinking": {"type": "disabled"}}),
    )
    for name, identifier, extra_params in defaults:
        model = tomlkit.table()
        model.update({
            "name": name,
            "model_identifier": identifier,
            "model_type": "llm",
            "api_provider": "DeepSeek",
            "visual": False,
            "extra_params": extra_params,
        })
        models.append(model)
    tasks = doc["model_task_config"]
    for task, names in _DEFAULT_CORE_TASK_MODELS.items():
        tasks[task]["model_list"] = names
    tasks["memory"]["model_list"] = []
    tasks["embedding"]["model_list"] = []
    tasks["replyer"]["selection_strategy"] = "random"
    tasks["replyer"]["max_tokens"] = 8192
    for task in ("fast_model", "image_embedding"):
        config = tomlkit.table()
        config["model_list"] = []
        tasks[task] = config
    return tomlkit.dumps(doc)


def test_sync_enabled_defaults_on_and_explicit_false_opts_out(monkeypatch):
    monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda _key: None)
    assert config_sync_enabled() is True
    for raw in ("0", "false", "no", "off"):
        monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda _key, raw=raw: raw)
        assert config_sync_enabled() is False
    monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda _key: "maybe-secret")
    with pytest.raises(ConfigSyncError) as error:
        config_sync_enabled()
    assert "maybe-secret" not in str(error.value)


def test_migrates_all_native_models_keys_and_route_order_once(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    _install_source(monkeypatch, tmp_path)

    assert sync_maibot_config(instance) is True
    doc = _model_doc(instance)
    providers = _rows_by_name(doc["api_providers"])
    models = _rows_by_name(doc["models"])
    tasks = doc["model_task_config"]

    assert not any(name in {"pb-route-chat", "pb-route-decision"} for name in models)
    assert {row["model_identifier"] for row in models.values()} >= {"chat-a", "chat-unused", "chat-b"}
    assert {row["api_key"] for name, row in providers.items() if name.startswith("pallas-import-")} == {
        CHAT_KEY_A,
        CHAT_KEY_B,
        CHAT_KEY_C,
        "sk-disabled",
    }
    assert [
        (models[name]["model_identifier"], providers[models[name]["api_provider"]]["api_key"])
        for name in tasks["replyer"]["model_list"]
    ] == [
        ("chat-a", CHAT_KEY_A),
        ("chat-a", CHAT_KEY_B),
        ("chat-b", CHAT_KEY_C),
    ]
    assert tasks["planner"]["model_list"] == tasks["replyer"]["model_list"]
    assert tasks["utils"]["model_list"] == tasks["replyer"]["model_list"][:2]
    assert tasks["replyer"]["selection_strategy"] == "sequential"
    assert tasks["memory"]["model_list"] == ["manual-model"]
    assert {row["model_identifier"] for row in models.values()} >= {"chat-a", "chat-b", "chat-unused", "chat-disabled"}
    assert (
        providers[next(row["api_provider"] for row in models.values() if row["model_identifier"] == "chat-a")][
            "auth_type"
        ]
        == "bearer"
    )
    assert _marker(instance)["version"] == 3
    assert sync_maibot_config(instance) is False


def test_default_placeholder_core_routes_are_replaced_with_imported_routes(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _default_native_model_fixture())
    _install_source(monkeypatch, tmp_path)
    original = _model_doc(instance)

    assert config_sync_preflight(instance)["ready"] is False
    assert sync_maibot_config(instance) is True

    migrated = _model_doc(instance)
    tasks = migrated["model_task_config"]
    for task in _DEFAULT_CORE_TASK_MODELS:
        assert tasks[task]["model_list"]
        assert not set(tasks[task]["model_list"]) & set(_DEFAULT_CORE_TASK_MODELS[task])
    assert tasks["replyer"]["selection_strategy"] == "sequential"
    assert tasks["replyer"]["max_tokens"] == original["model_task_config"]["replyer"]["max_tokens"]
    assert "your-api-key" not in {
        row["api_key"]
        for row in migrated["api_providers"]
        if row["name"]
        in {
            migrated_model["api_provider"]
            for migrated_model in migrated["models"]
            if migrated_model["name"] in tasks["replyer"]["model_list"]
        }
    }
    assert config_sync_preflight(instance)["ready"] is True


def test_native_task_allowlist_matches_pinned_model_task_config_fields():
    assert config_sync._NATIVE_TASKS == _EXPECTED_NATIVE_TASKS


def test_unavailable_core_route_fails_before_marker_and_can_retry(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _default_native_model_fixture())
    unsupported = _source_document(
        providers=[_provider("unsupported", request_method="anthropic_messages", models=[{"name": "only-model"}])],
        routes={"llm_chat": ["unsupported"], "turn_decision": ["unsupported"]},
    )
    endpoints = {
        "llm_chat": [_endpoint("unsupported", "only-model", URL_A, (CHAT_KEY_A,))],
        "turn_decision": [_endpoint("unsupported", "only-model", URL_A, (CHAT_KEY_A,))],
    }
    _install_source(monkeypatch, tmp_path, document=unsupported, endpoints=endpoints)
    before = _snapshot(instance)

    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before
    assert not (instance / "config" / config_sync.MARKER_FILENAME).exists()

    supported = _source_document(
        providers=[_provider("supported", models=[{"name": "only-model"}])],
        routes={"llm_chat": ["supported"], "turn_decision": ["supported"]},
    )
    endpoint = _endpoint("supported", "only-model", URL_A, (CHAT_KEY_A,))
    monkeypatch.setattr(config_sync.providers_store, "load_providers_document", lambda **_kwargs: supported)
    monkeypatch.setattr(
        config_sync.providers_store,
        "resolve_endpoint_candidates_for_task",
        lambda task: [endpoint],
    )
    assert sync_maibot_config(instance) is True
    assert _marker(instance)["version"] == 3
    assert config_sync_preflight(instance)["ready"] is True


def test_daily_caps_warn_but_do_not_block_and_cny_pricing_migrates(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    source = _source_document()
    source["providers"][0]["daily_tokens_cap"] = 1000
    source["providers"][0]["model_pricing"] = {"chat-a": {"price_in": 0.5, "price_out": 1.2, "cache_price_in": 0.1}}
    source["routing"]["cost_currency"] = "CNY"
    _install_source(monkeypatch, tmp_path, document=source)

    assert sync_maibot_config(instance) is True
    report = config_sync_preflight(instance)
    assert report["ready"] is True
    assert "daily_limits_not_migrated" in report["warnings"]
    imported = [row for row in _model_doc(instance)["models"] if row["model_identifier"] == "chat-a"]
    assert imported
    assert all((row["price_in"], row["price_out"], row["cache_price_in"]) == (0.5, 1.2, 0.1) for row in imported)


def test_unsupported_protocol_is_reported_without_protocol_substitution(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    source = _source_document(
        providers=[_provider("anthropic", request_method="anthropic_messages")],
        routes={"llm_chat": ["anthropic"], "turn_decision": ["anthropic"]},
    )
    endpoints = {
        "llm_chat": [_endpoint("anthropic", "chat-a", URL_A, (CHAT_KEY_A,))],
        "turn_decision": [_endpoint("anthropic", "chat-a", URL_A, (CHAT_KEY_A,))],
    }
    _install_source(monkeypatch, tmp_path, document=source, endpoints=endpoints)
    before = _snapshot(instance)

    with pytest.raises(ConfigSyncError, match="core_task_model_missing"):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before
    assert not (instance / "config" / config_sync.MARKER_FILENAME).exists()
    assert "unsupported_request_method" in config_sync._build_plan(_model_doc(instance))["warnings"]
    assert config_sync_preflight(instance)["ready"] is False


def test_legacy_env_fallback_migrates_credentials_and_model(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    empty = {"providers": [], "routing": {"tasks": {}, "task_backups": {}, "tier_backups": {}, "chain_fallback": []}}
    cfg = SimpleNamespace(
        llm_base_url=URL_A,
        llm_model="legacy-chat",
        llm_api_key=CHAT_KEY_A,
        llm_chat_daily_calls_limit=0,
        llm_chat_daily_tokens_limit=0,
        llm_embedding_provider="stub",
        llm_embedding_base_url="",
        llm_embedding_api_key="",
        llm_embedding_provider_id="",
    )
    _install_source(monkeypatch, tmp_path, document=empty, endpoints={"llm_chat": [], "turn_decision": []}, config=cfg)

    sync_maibot_config(instance)
    doc = _model_doc(instance)
    models = _rows_by_name(doc["models"])
    providers = _rows_by_name(doc["api_providers"])
    route = doc["model_task_config"]["replyer"]["model_list"]
    assert len(route) == 1
    assert models[route[0]]["model_identifier"] == "legacy-chat"
    assert providers[models[route[0]]["api_provider"]]["api_key"] == CHAT_KEY_A
    assert config_sync_preflight(instance)["ready"] is True


def test_keyless_provider_migrates_models_and_resolver_default_route(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    row = _provider("public", api_keys=[], models=[{"name": "public-chat"}])
    document = {
        "providers": [row],
        "routing": {"tasks": {}, "task_backups": {}, "tier_backups": {}, "chain_fallback": []},
    }
    endpoint = _endpoint("public", "public-chat", URL_A, ())
    _install_source(
        monkeypatch,
        tmp_path,
        document=document,
        endpoints={"llm_chat": [endpoint], "turn_decision": [endpoint]},
    )

    sync_maibot_config(instance)
    doc = _model_doc(instance)
    models = _rows_by_name(doc["models"])
    providers = _rows_by_name(doc["api_providers"])
    route = doc["model_task_config"]["replyer"]["model_list"]
    assert len(route) == 1
    assert models[route[0]]["model_identifier"] == "public-chat"
    assert providers[models[route[0]]["api_provider"]]["auth_type"] == "none"
    assert providers[models[route[0]]["api_provider"]]["api_key"] == ""


def test_remote_embedding_imports_each_key_and_does_not_copy_proxy_alias(tmp_path, monkeypatch):
    instance = _instance(tmp_path, MODEL_CONFIG.replace('model_list = ["manual-embedding"]', "model_list = []"))
    _install_source(
        monkeypatch,
        tmp_path,
        embedding={
            "base_url": URL_B,
            "model": "text-embed",
            "provider_id": "embed",
            "api_keys": [EMBED_KEY_A, "sk-embed-key-b"],
        },
    )

    sync_maibot_config(instance)
    doc = _model_doc(instance)
    models = _rows_by_name(doc["models"])
    providers = _rows_by_name(doc["api_providers"])
    embedding_names = doc["model_task_config"]["embedding"]["model_list"]
    assert [providers[models[name]["api_provider"]]["api_key"] for name in embedding_names] == [
        EMBED_KEY_A,
        "sk-embed-key-b",
    ]
    assert all(models[name]["model_identifier"] == "text-embed" for name in embedding_names)
    assert not any(row["client_type"] == "pallas-managed" for row in providers.values())


def test_local_embedding_is_reported_not_replaced_with_a_stub(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    _install_source(monkeypatch, tmp_path, embedding={"unsupported": "local_embedding_not_migrated"})

    sync_maibot_config(instance)
    doc = _model_doc(instance)
    assert doc["model_task_config"]["embedding"]["model_list"] == ["manual-embedding"]
    assert "local_embedding_not_migrated" in config_sync_preflight(instance)["warnings"]
    assert not any(row["model_type"] == "stub" for row in doc["models"])


def test_existing_native_config_and_marker_stop_source_reads_and_writes(tmp_path, monkeypatch):
    native = tomlkit.parse(MODEL_CONFIG)
    native["model_task_config"]["replyer"]["model_list"] = ["manual-model"]
    native["model_task_config"]["planner"]["model_list"] = ["manual-model"]
    native["model_task_config"]["utils"]["model_list"] = ["manual-model"]
    instance = _instance(tmp_path, tomlkit.dumps(native))
    _install_source(monkeypatch, tmp_path, document={"providers": [], "routing": {}})
    assert sync_maibot_config(instance) is True
    migrated_tasks = _model_doc(instance)["model_task_config"]
    assert migrated_tasks["replyer"]["model_list"] == ["manual-model"]
    assert migrated_tasks["planner"]["model_list"] == ["manual-model"]
    assert migrated_tasks["utils"]["model_list"] == ["manual-model"]

    model_path = instance / "config" / MODEL_CONFIG_FILENAME
    edited = tomlkit.parse(model_path.read_text(encoding="utf-8"))
    edited["api_providers"][0]["max_retry"] = 9
    model_path.write_text(tomlkit.dumps(edited), encoding="utf-8")
    changed = _snapshot(instance)
    mtimes = {path.name: path.stat().st_mtime_ns for path in (instance / "config").iterdir()}
    monkeypatch.setattr(config_sync, "get_llm_config", lambda: (_ for _ in ()).throw(AssertionError("source read")))
    monkeypatch.setattr(
        config_sync.providers_store,
        "load_providers_document",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("source read")),
    )
    monkeypatch.setattr(
        config_sync, "load_base_system_prompt", lambda: (_ for _ in ()).throw(AssertionError("source read"))
    )

    assert sync_maibot_config(instance) is False
    assert config_sync_preflight(instance)["ready"] is True
    assert _snapshot(instance) == changed
    assert {path.name: path.stat().st_mtime_ns for path in (instance / "config").iterdir()} == mtimes


def test_preflight_accepts_native_edits_and_checks_core_model_provider_refs(tmp_path):
    native = tomlkit.parse(MODEL_CONFIG)
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    instance = _instance(tmp_path, tomlkit.dumps(native))

    assert config_sync_preflight(instance)["ready"] is True
    native["models"][0]["api_provider"] = "missing-provider"
    (instance / "config" / MODEL_CONFIG_FILENAME).write_text(tomlkit.dumps(native), encoding="utf-8")
    report = config_sync_preflight(instance)
    assert report["ready"] is False
    assert "undefined_provider_reference" in report["reasons"]


@pytest.mark.parametrize("missing_task", ["replyer", "planner", "utils", "model_task_config"])
def test_preflight_rejects_missing_core_task_tables(tmp_path, missing_task):
    native = tomlkit.parse(MODEL_CONFIG)
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    if missing_task == "model_task_config":
        del native["model_task_config"]
    else:
        del native["model_task_config"][missing_task]
    instance = _instance(tmp_path, tomlkit.dumps(native))

    report = config_sync_preflight(instance)

    assert report["ready"] is False
    assert "core_task_model_missing" in report["reasons"]


def test_preflight_accepts_native_image_embedding_for_both_embedding_tasks(tmp_path):
    native = tomlkit.parse(MODEL_CONFIG)
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    image_model = tomlkit.table()
    image_model.update({
        "name": "manual-image-embedding",
        "model_identifier": "manual-image-embedding",
        "model_type": "image_embedding",
        "api_provider": "manual-provider",
    })
    native["models"].append(image_model)
    native["model_task_config"]["embedding"]["model_list"] = ["manual-image-embedding"]
    image_task = tomlkit.table()
    image_task["model_list"] = ["manual-image-embedding"]
    native["model_task_config"]["image_embedding"] = image_task
    instance = _instance(tmp_path, tomlkit.dumps(native))

    report = config_sync_preflight(instance)

    assert report["ready"] is True
    assert report["reasons"] == []


def test_preflight_accepts_native_plugin_client_without_reading_pallas_sources(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _default_native_model_fixture())
    report = config_sync_preflight(instance)
    assert report["ready"] is False
    assert "placeholder_provider_key" in report["reasons"]

    native = tomlkit.parse(_default_native_model_fixture())
    native["api_providers"][0]["api_key"] = "synthetic-native-key"
    native["api_providers"][0]["client_type"] = "native-plugin-client"
    (instance / "config" / MODEL_CONFIG_FILENAME).write_text(tomlkit.dumps(native), encoding="utf-8")
    monkeypatch.setattr(config_sync, "get_llm_config", _fail_source_read)
    monkeypatch.setattr(config_sync, "load_base_system_prompt", _fail_source_read)
    monkeypatch.setattr(config_sync.providers_store, "providers_store_path", _fail_source_read)
    monkeypatch.setattr(config_sync.providers_store, "load_providers_document", _fail_source_read)
    monkeypatch.setattr(config_sync.providers_store, "resolve_endpoint_candidates_for_task", _fail_source_read)

    report = config_sync_preflight(instance)
    assert report["ready"] is True
    assert report["reasons"] == []

    native["api_providers"][0]["client_type"] = ["not", "a", "string"]
    (instance / "config" / MODEL_CONFIG_FILENAME).write_text(tomlkit.dumps(native), encoding="utf-8")
    report = config_sync_preflight(instance)
    assert report["ready"] is False
    assert "invalid_provider_client_type" in report["reasons"]


@pytest.mark.parametrize("invalid_native", ["missing_core", "placeholder_key"])
def test_v1_marker_requires_valid_native_config_and_can_retry_without_source_reads(
    tmp_path, monkeypatch, invalid_native
):
    native = tomlkit.parse(MODEL_CONFIG)
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    if invalid_native == "missing_core":
        del native["model_task_config"]
    else:
        native["api_providers"][0]["api_key"] = "your-api-key"
    instance = _instance(tmp_path, tomlkit.dumps(native))
    marker_path = instance / "config" / config_sync.MARKER_FILENAME
    marker_path.write_text(json.dumps(_v1_marker()), encoding="utf-8")
    before = _snapshot(instance)
    monkeypatch.setattr(config_sync, "get_llm_config", _fail_source_read)
    monkeypatch.setattr(config_sync, "load_base_system_prompt", _fail_source_read)
    monkeypatch.setattr(config_sync.providers_store, "providers_store_path", _fail_source_read)
    monkeypatch.setattr(config_sync.providers_store, "load_providers_document", _fail_source_read)
    monkeypatch.setattr(config_sync.providers_store, "resolve_endpoint_candidates_for_task", _fail_source_read)

    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before

    native = tomlkit.parse((instance / "config" / MODEL_CONFIG_FILENAME).read_text(encoding="utf-8"))
    tasks = native.setdefault("model_task_config", tomlkit.table())
    for task in ("replyer", "planner", "utils"):
        task_config = tasks.setdefault(task, tomlkit.table())
        task_config["model_list"] = ["manual-model"]
    native["api_providers"][0]["api_key"] = "synthetic-repaired-key"
    (instance / "config" / MODEL_CONFIG_FILENAME).write_text(tomlkit.dumps(native), encoding="utf-8")

    assert sync_maibot_config(instance) is True
    assert _marker(instance)["version"] == 3


def test_config_migration_completed_validates_only_v3_marker(tmp_path):
    instance = _instance(tmp_path)
    assert config_sync.config_migration_completed(instance) is False

    marker_path = instance / "config" / config_sync.MARKER_FILENAME
    marker_path.write_text(json.dumps(_v1_marker()), encoding="utf-8")
    assert config_sync.config_migration_completed(instance) is False

    marker_path.write_text(config_sync._marker_text(), encoding="utf-8")
    assert config_sync.config_migration_completed(instance) is True

    marker_path.write_text('{"version": 3}', encoding="utf-8")
    with pytest.raises(ConfigSyncError, match="unsupported"):
        config_sync.config_migration_completed(instance)


def test_preflight_does_not_reapply_pallas_feature_gates(tmp_path):
    native = tomlkit.parse(MODEL_CONFIG)
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    instance = _instance(tmp_path, tomlkit.dumps(native))
    bot_path = instance / "config" / BOT_CONFIG_FILENAME
    bot_path.write_text(
        BOT_CONFIG + "\n[voice]\nenable_asr = true\n\n[a_memorix.plugin]\nenabled = true\n",
        encoding="utf-8",
    )

    report = config_sync_preflight(instance)
    assert report["ready"] is True
    assert report["reasons"] == []


def test_valid_native_config_without_legacy_source_is_preserved(tmp_path, monkeypatch):
    native = tomlkit.parse(MODEL_CONFIG)
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    instance = _instance(tmp_path, tomlkit.dumps(native))
    source_file = tmp_path / "absent.json"
    monkeypatch.setattr(config_sync.providers_store, "providers_store_path", lambda: source_file)
    monkeypatch.setattr(
        config_sync.providers_store,
        "load_providers_document",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not seed or read missing catalog")),
    )
    monkeypatch.setattr(
        config_sync,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_base_url="",
            llm_model="",
            llm_api_key="",
            llm_chat_daily_calls_limit=0,
            llm_chat_daily_tokens_limit=0,
            llm_embedding_provider="stub",
            llm_embedding_base_url="",
            llm_embedding_api_key="",
            llm_embedding_provider_id="",
        ),
    )
    before_model = (instance / "config" / MODEL_CONFIG_FILENAME).read_bytes()
    assert sync_maibot_config(instance) is True
    assert (instance / "config" / MODEL_CONFIG_FILENAME).read_bytes() == before_model
    assert config_sync_preflight(instance)["ready"] is True


def test_v3_marker_rejects_unknown_shape_and_does_not_reimport(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    _install_source(monkeypatch, tmp_path)
    sync_maibot_config(instance)
    marker_path = instance / "config" / config_sync.MARKER_FILENAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["version"] = 91
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(ConfigSyncError, match="unsupported"):
        sync_maibot_config(instance)


def test_v1_migration_marker_is_upgraded_without_overwriting_native_toml(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    config_dir = instance / "config"
    native = tomlkit.parse((config_dir / MODEL_CONFIG_FILENAME).read_text(encoding="utf-8"))
    for task in ("replyer", "planner", "utils"):
        native["model_task_config"][task]["model_list"] = ["manual-model"]
    (config_dir / MODEL_CONFIG_FILENAME).write_text(tomlkit.dumps(native), encoding="utf-8")
    before = {name: (config_dir / name).read_bytes() for name in (BOT_CONFIG_FILENAME, MODEL_CONFIG_FILENAME)}
    (config_dir / config_sync.MARKER_FILENAME).write_text(json.dumps(_v1_marker()), encoding="utf-8")
    monkeypatch.setattr(config_sync, "get_llm_config", lambda: (_ for _ in ()).throw(AssertionError("source read")))

    assert sync_maibot_config(instance) is True
    assert _marker(instance)["version"] == 3
    assert config_sync.config_migration_completed(instance) is True
    assert {name: (config_dir / name).read_bytes() for name in before} == before


def test_v2_aliases_are_replaced_by_native_sources_and_only_aliases_removed(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _native_alias_fixture())
    config_dir = instance / "config"
    (config_dir / config_sync.MARKER_FILENAME).write_text(
        json.dumps({
            "version": 2,
            "bot_config_version": "8.15.47",
            "model_config_version": "1.17.24",
            "digest": "b" * 64,
            "budget_policy": "native-cycle+pallas-request-v1",
            "provider_names": ["pallas-managed"],
            "model_names": ["pb-route-chat", "pb-route-decision"],
            "task_keys": ["replyer", "planner", "utils"],
            "updated_at": "2026-01-01T00:00:00Z",
        }),
        encoding="utf-8",
    )
    _install_source(monkeypatch, tmp_path)

    sync_maibot_config(instance)
    doc = _model_doc(instance)
    assert "pallas-managed" not in {row["name"] for row in doc["api_providers"]}
    assert not {"pb-route-chat", "pb-route-decision"} & {row["name"] for row in doc["models"]}
    assert doc["model_task_config"]["replyer"]["model_list"]
    assert doc["model_task_config"]["memory"]["model_list"] == ["manual-model"]
    assert _marker(instance)["version"] == 3


def test_v2_alias_conflict_and_unmarked_proxy_alias_are_rejected_without_writes(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _native_alias_fixture())
    config_dir = instance / "config"
    (config_dir / config_sync.MARKER_FILENAME).write_text(
        json.dumps({
            "version": 2,
            "bot_config_version": "8.15.47",
            "model_config_version": "1.17.24",
            "digest": "b" * 64,
            "budget_policy": "native-cycle+pallas-request-v1",
            "provider_names": ["pallas-managed"],
            "model_names": ["pb-route-chat", "pb-route-decision"],
            "task_keys": ["replyer", "planner", "utils"],
            "updated_at": "2026-01-01T00:00:00Z",
        }),
        encoding="utf-8",
    )
    model_path = config_dir / MODEL_CONFIG_FILENAME
    doc = tomlkit.parse(model_path.read_text(encoding="utf-8"))
    next(row for row in doc["api_providers"] if row["name"] == "pallas-managed")["base_url"] = "https://changed.invalid"
    model_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    _install_source(monkeypatch, tmp_path)
    before = _snapshot(instance)

    with pytest.raises(ConfigSyncError, match="conflict"):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_unmarked_proxy_alias_is_rejected_without_writes(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _native_alias_fixture())
    _install_source(monkeypatch, tmp_path)
    before = _snapshot(instance)

    with pytest.raises(ConfigSyncError, match="unmarked"):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_first_migration_backup_is_0600_and_dry_run_writes_nothing(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    _install_source(monkeypatch, tmp_path)
    before = _snapshot(instance)

    report = sync_maibot_config(instance, dry_run=True)
    assert report["ready"] is True
    assert report["reasons"] == []
    assert isinstance(report["warnings"], list)
    assert _snapshot(instance) == before
    assert not (instance / "config" / config_sync.MARKER_FILENAME).exists()
    assert sync_maibot_config(instance) is True
    for filename in (BOT_CONFIG_FILENAME, MODEL_CONFIG_FILENAME):
        backup = instance / "config" / f"{filename}.pallas-backup"
        assert backup.is_file()
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        assert stat.S_IMODE((instance / "config" / filename).stat().st_mode) == 0o600


def test_dry_run_reports_rendered_default_route_readiness_without_writes(tmp_path, monkeypatch):
    instance = _instance(tmp_path, _default_native_model_fixture())
    _install_source(monkeypatch, tmp_path)
    before = _snapshot(instance)

    report = sync_maibot_config(instance, dry_run=True)

    assert report["ready"] is True
    assert report["reasons"] == []
    assert config_sync_preflight(instance)["ready"] is False
    assert _snapshot(instance) == before
    assert not (instance / "config" / config_sync.MARKER_FILENAME).exists()


def test_first_takeover_rejects_conflicting_backup_without_touching_configs(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    _install_source(monkeypatch, tmp_path)
    backup = instance / "config" / f"{MODEL_CONFIG_FILENAME}.pallas-backup"
    backup.write_text("different", encoding="utf-8")
    backup.chmod(0o600)
    before = _snapshot(instance)

    with pytest.raises(ConfigSyncError, match="backup differs"):
        sync_maibot_config(instance)
    after = _snapshot(instance)
    assert after[BOT_CONFIG_FILENAME] == before[BOT_CONFIG_FILENAME]
    assert after[MODEL_CONFIG_FILENAME] == before[MODEL_CONFIG_FILENAME]
    assert not (instance / "config" / config_sync.MARKER_FILENAME).exists()


def test_symlink_and_write_failure_are_safe_and_rollback_marker(tmp_path, monkeypatch):
    instance = _instance(tmp_path)
    _install_source(monkeypatch, tmp_path)
    model = instance / "config" / MODEL_CONFIG_FILENAME
    original = model.read_bytes()
    outside = tmp_path / "outside.toml"
    outside.write_bytes(original)
    model.unlink()
    model.symlink_to(outside)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert outside.read_bytes() == original

    model.unlink()
    model.write_bytes(original)
    marker_path = instance / "config" / config_sync.MARKER_FILENAME
    marker_path.write_text(
        json.dumps({
            "version": 2,
            "bot_config_version": "8.15.47",
            "model_config_version": "1.17.24",
            "digest": "b" * 64,
            "budget_policy": "native-cycle+pallas-request-v1",
            "provider_names": ["pallas-managed"],
            "model_names": ["pb-route-chat", "pb-route-decision"],
            "task_keys": ["replyer", "planner", "utils"],
            "updated_at": "2026-01-01T00:00:00Z",
        }),
        encoding="utf-8",
    )
    alias_instance = _instance(tmp_path / "alias", _native_alias_fixture())
    alias_dir = alias_instance / "config"
    marker_path = alias_dir / config_sync.MARKER_FILENAME
    marker_path.write_text(
        json.dumps({
            "version": 2,
            "bot_config_version": "8.15.47",
            "model_config_version": "1.17.24",
            "digest": "b" * 64,
            "budget_policy": "native-cycle+pallas-request-v1",
            "provider_names": ["pallas-managed"],
            "model_names": ["pb-route-chat", "pb-route-decision"],
            "task_keys": ["replyer", "planner", "utils"],
            "updated_at": "2026-01-01T00:00:00Z",
        }),
        encoding="utf-8",
    )
    _install_source(monkeypatch, tmp_path / "alias")
    before = _snapshot(alias_instance)
    original_write = config_sync._write_text_0600
    failed = False

    def fail_on_marker(path: Path, text: str) -> None:
        nonlocal failed
        if path.name == config_sync.MARKER_FILENAME and not failed:
            failed = True
            raise OSError("synthetic write failure")
        original_write(path, text)

    monkeypatch.setattr(config_sync, "_write_text_0600", fail_on_marker)
    with pytest.raises(OSError, match="synthetic write failure"):
        sync_maibot_config(alias_instance)
    after = _snapshot(alias_instance)
    assert after[config_sync.MARKER_FILENAME] == before[config_sync.MARKER_FILENAME]
    assert after[BOT_CONFIG_FILENAME] == before[BOT_CONFIG_FILENAME]
    assert after[MODEL_CONFIG_FILENAME] == before[MODEL_CONFIG_FILENAME]


@pytest.mark.skipif(
    os.environ.get("PALLAS_MAIBOT_NATIVE_PROOF") != "1",
    reason="set PALLAS_MAIBOT_NATIVE_PROOF=1 to use the frozen MaiBot source/environment",
)
def test_opt_in_native_default_template_selection_and_http_proof(tmp_path, monkeypatch):
    assert _DEFAULT_NATIVE_TEMPLATE.is_file()
    assert _NATIVE_SOURCE.is_dir()
    assert _NATIVE_PYTHON.is_file()
    instance = _instance(tmp_path, _DEFAULT_NATIVE_TEMPLATE.read_text(encoding="utf-8"))
    providers = [
        _provider("proof-a", base_url=URL_A, api_keys=[CHAT_KEY_A, CHAT_KEY_B], models=[{"name": "migrated-a"}]),
        _provider("proof-b", base_url=URL_B, api_keys=[CHAT_KEY_C], models=[{"name": "migrated-b"}]),
    ]
    document = _source_document(
        providers=providers,
        routes={"llm_chat": ["proof-a", "proof-b"], "turn_decision": ["proof-a"]},
    )
    endpoints = {
        "llm_chat": [
            _endpoint("proof-a", "migrated-a", URL_A, (CHAT_KEY_A, CHAT_KEY_B)),
            _endpoint("proof-b", "migrated-b", URL_B, (CHAT_KEY_C,)),
        ],
        "turn_decision": [_endpoint("proof-a", "migrated-a", URL_A, (CHAT_KEY_A, CHAT_KEY_B))],
    }
    _install_source(monkeypatch, tmp_path, document=document, endpoints=endpoints)
    assert sync_maibot_config(instance) is True
    assert config_sync_preflight(instance)["ready"] is True
    model_path = instance / "config" / MODEL_CONFIG_FILENAME
    imported_routes = _model_doc(instance)["model_task_config"]["replyer"]["model_list"]
    assert len(imported_routes) == 3
    assert all(name.startswith("pallas-import-model-") for name in imported_routes)

    native_script = textwrap.dedent(
        """
        import asyncio
        import json
        import os
        import socket
        import sys
        import tomllib
        from pathlib import Path

        payload = json.load(sys.stdin)
        sys.path.insert(0, payload["source"])
        os.environ["MAIBOT_INITIALIZE_ONLY"] = "1"
        os.environ["MAIBOT_INSTANCE_DIR"] = payload["instance"]

        def deny_socket(*_args, **_kwargs):
            raise RuntimeError("native proof socket egress blocked")

        socket.socket.connect = deny_socket
        socket.socket.connect_ex = deny_socket
        socket.create_connection = deny_socket

        import httpx
        from src.config.config import ModelConfig, config_manager

        model_data = tomllib.loads(Path(payload["model_config"]).read_text(encoding="utf-8"))
        model_data.pop("inner", None)
        native_config = ModelConfig(**model_data)
        config_manager.model_config = native_config

        from src.llm_models.model_client import openai_client
        from src.llm_models.model_client.base_client import RequestTraceContext
        from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
        from src.llm_models.utils_model import LLMOrchestrator

        source_module = Path(openai_client.__file__).resolve()
        if Path(payload["source"]).resolve() not in source_module.parents:
            raise RuntimeError("native proof did not import the frozen source tree")

        http_events = []

        def mock_response(request):
            body = json.loads(request.content.decode("utf-8"))
            http_events.append({
                "url": str(request.url),
                "authorization": request.headers.get("authorization", ""),
                "model": body.get("model"),
            })
            return httpx.Response(200, request=request, json={
                "id": "chatcmpl-native-proof",
                "object": "chat.completion",
                "created": 1,
                "model": body.get("model", ""),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "native mock response"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })

        class MockNativeHttpClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(mock_response)
                kwargs["trust_env"] = False
                super().__init__(*args, **kwargs)

        openai_client.DefaultAsyncHttpxClient = MockNativeHttpClient
        expected = payload["expected"]

        async def prove_routes():
            excluded = set()
            results = []
            for route in expected:
                orchestrator = LLMOrchestrator("replyer", request_type="config-sync-native-proof")
                model, provider, client = await orchestrator._select_model(exclude_models=excluded)
                context = ContextItemBuilder().set_role(RoleType.User).add_text_part("synthetic proof").build()
                request = orchestrator._build_response_request(
                    model_info=model,
                    context_items=[context],
                    tool_options=None,
                    response_format=None,
                    stream_response_handler=None,
                    async_response_parser=None,
                    interrupt_flag=None,
                    temperature=0.1,
                    max_tokens=8,
                    trace_context=RequestTraceContext(task_name="replyer", request_type="native-proof"),
                )
                await client.get_response(request)
                event = http_events[-1]
                results.append({
                    "selected_model": model.name,
                    "model_identifier_matches": model.model_identifier == route["model"],
                    "provider_matches": provider.name.startswith("pallas-import-provider-"),
                    "endpoint_matches": provider.base_url == route["base_url"],
                    "key_matches": provider.api_key == route["key"],
                    "request_model_matches": event["model"] == route["model"],
                    "request_url_matches": event["url"].startswith(route["base_url"].rstrip("/") + "/chat/completions"),
                    "request_auth_matches": event["authorization"] == "Bearer " + route["key"],
                })
                excluded.add(model.name)
            return results

        results = asyncio.run(prove_routes())
        print(json.dumps({"source_module": str(source_module), "task_fields": sorted(
            name for name, field in native_config.model_task_config.__class__.model_fields.items()
            if field.annotation.__name__ == "TaskConfig"
        ), "results": results}, ensure_ascii=False))
        """
    )
    expected_routes = [
        {"model": "migrated-a", "base_url": URL_A, "key": CHAT_KEY_A},
        {"model": "migrated-a", "base_url": URL_A, "key": CHAT_KEY_B},
        {"model": "migrated-b", "base_url": URL_B, "key": CHAT_KEY_C},
    ]
    native_instance = tmp_path / "native-instance"
    native_instance.mkdir()
    payload = {
        "source": str(_NATIVE_SOURCE),
        "instance": str(native_instance),
        "model_config": str(model_path),
        "expected": expected_routes,
    }
    env = {
        "HOME": str(tmp_path),
        "PATH": os.defpath,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [str(_NATIVE_PYTHON), "-c", native_script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=90,
        cwd=tmp_path,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert set(result["task_fields"]) == _EXPECTED_NATIVE_TASKS
    assert len(result["results"]) == len(expected_routes)
    assert all(all(value for key, value in row.items() if key != "selected_model") for row in result["results"])
    report_path = tmp_path / "native-proof-report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"native MaiBot proof report: {report_path}")
