"""Focused tests for the MaiBot managed config sync (synthetic sources only)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pallas.product.agent_bridge import config_sync
from pallas.product.agent_bridge.config_sync import (
    BOT_CONFIG_FILENAME,
    MODEL_CONFIG_FILENAME,
    ConfigSyncError,
    config_sync_enabled,
    sync_maibot_config,
)
from pallas.product.llm.providers_store import ResolvedLlmEndpoint

_CHAT_SECRET = "sk-chat-secret-do-not-leak"
_EMBED_SECRET = "sk-embed-secret-do-not-leak"

_BOT_TOML = """# keep this comment
[inner]
version = "8.15.47"

[bot]
nickname = "麦麦"
alias_names = []
extra_note = "keep-me"

[personality]
personality = "old persona"
behavior_style = "keep behavior"
reply_style = "keep reply"
"""

_MODEL_TOML = """# model config comment
[inner]
version = "1.17.24"

[[api_providers]]
name = "manual-provider"
base_url = "https://manual.example.com/v1"
api_key = "manual-key"
client_type = "openai"
auth_type = "bearer"

[[models]]
name = "manual-model"
model_identifier = "manual-x"
model_type = "llm"
api_provider = "manual-provider"
extra_params = { foo = "bar" }

[[models]]
name = "manual-embedding"
model_identifier = "manual-embed"
model_type = "embedding"
api_provider = "manual-provider"

[model_task_config.replyer]
model_list = ["manual-model"]
max_tokens = 2048
hard_timeout = 111.0

[model_task_config.vlm]
model_list = ["manual-model"]

[model_task_config.embedding]
model_list = ["manual-embedding"]
"""


def _make_instance(tmp_path: Path, *, bot_toml: str = _BOT_TOML, model_toml: str = _MODEL_TOML) -> Path:
    instance = tmp_path / "instance"
    (instance / "config").mkdir(parents=True)
    (instance / "config" / BOT_CONFIG_FILENAME).write_text(bot_toml, encoding="utf-8")
    (instance / "config" / MODEL_CONFIG_FILENAME).write_text(model_toml, encoding="utf-8")
    return instance


def _chat_row(provider_id: str = "prov-a", **overrides):
    row = {
        "id": provider_id,
        "kind": "remote",
        "base_url": "https://api.example.com/v1",
        "api_key": _CHAT_SECRET,
        "api_keys": [_CHAT_SECRET],
        "api_key_env": "",
        "default_model": "gpt-x",
        "models": [{"name": "gpt-x", "capabilities": ["text"], "model_effort": "disable"}],
        "enabled": True,
        "task_models": {"llm_chat": "gpt-x", "turn_decision": "gpt-small"},
        "capabilities": ["text"],
        "model_effort": "disable",
        "request_method": "chat_completions",
        "daily_tokens_cap": 0,
        "daily_cost_cap": 0.0,
    }
    row.update(overrides)
    return row


def _endpoint(provider_id: str = "prov-a", model: str = "gpt-x", **overrides) -> ResolvedLlmEndpoint:
    kwargs = {
        "provider_id": provider_id,
        "base_url": "https://api.example.com/v1",
        "api_key": _CHAT_SECRET,
        "model": model,
        "capabilities": ("text",),
        "model_effort": "disable",
        "request_method": "chat_completions",
        "api_keys": (_CHAT_SECRET,),
    }
    kwargs.update(overrides)
    return ResolvedLlmEndpoint(**kwargs)


def _default_chains() -> dict[str, list[ResolvedLlmEndpoint]]:
    return {
        "llm_chat": [_endpoint("prov-a", "gpt-x")],
        "turn_decision": [_endpoint("prov-a", "gpt-small")],
    }


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chains: dict | None = None,
    rows: dict | None = None,
    persona: str = "SHARED CORE PROMPT",
    aliases: tuple[str, ...] = ("牛牛",),
    budget: tuple[int, int] = (0, 0),
    legacy: tuple[str, str, str] = ("", "", ""),
    embedding: tuple[str, str, str, str] | None = None,
    patch_persona: bool = True,
) -> None:
    chains = chains if chains is not None else _default_chains()
    rows = rows if rows is not None else {"prov-a": _chat_row()}
    if patch_persona:
        monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: persona)
    monkeypatch.setattr(config_sync, "extract_generic_self_aliases", lambda: list(aliases))
    monkeypatch.setattr(config_sync, "resolve_endpoint_candidates_for_task", lambda task: list(chains.get(task, [])))
    monkeypatch.setattr(config_sync, "find_provider", lambda pid: rows.get(pid))
    monkeypatch.setattr(
        config_sync,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_chat_daily_calls_limit=budget[0],
            llm_chat_daily_tokens_limit=budget[1],
            llm_base_url=legacy[0],
            llm_model=legacy[1],
            llm_api_key=legacy[2],
        ),
    )
    if embedding is None:
        monkeypatch.setattr(config_sync, "resolve_embedding_provider_name", lambda cfg: "stub")
    else:
        monkeypatch.setattr(config_sync, "resolve_embedding_provider_name", lambda cfg: "openai")
        monkeypatch.setattr(config_sync, "resolve_embedding_http_endpoint", lambda cfg: embedding[:3])
        monkeypatch.setattr(config_sync, "resolve_remote_embedding_model", lambda cfg: embedding[3])


def _read_model(instance: Path) -> dict:
    return tomllib.loads((instance / "config" / MODEL_CONFIG_FILENAME).read_text(encoding="utf-8"))


def _read_bot(instance: Path) -> dict:
    return tomllib.loads((instance / "config" / BOT_CONFIG_FILENAME).read_text(encoding="utf-8"))


def _model_by_name(instance: Path, name: str) -> dict:
    for row in _read_model(instance)["models"]:
        if row["name"] == name:
            return row
    raise AssertionError(f"model {name} missing")


def _provider_by_name(instance: Path, name: str) -> dict:
    for row in _read_model(instance)["api_providers"]:
        if row["name"] == name:
            return row
    raise AssertionError(f"provider {name} missing")


def _assert_references(instance: Path) -> None:
    model = _read_model(instance)
    provider_names = {row["name"] for row in model["api_providers"]}
    model_names = {row["name"] for row in model["models"]}
    for row in model["models"]:
        assert row["api_provider"] in provider_names
    for key, config in model["model_task_config"].items():
        if not isinstance(config, dict):
            continue
        for name in config.get("model_list") or []:
            assert name in model_names, f"{key} references undefined model {name}"


# --- config_sync_enabled ---------------------------------------------------


def test_config_sync_enabled_default_and_variants(monkeypatch):
    monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda key: None)
    assert config_sync_enabled() is False
    monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda key: "")
    assert config_sync_enabled() is False
    for raw in ("1", "true", "YES", "On"):
        monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda key, raw=raw: raw)
        assert config_sync_enabled() is True
    for raw in ("0", "false", "No", "off"):
        monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda key, raw=raw: raw)
        assert config_sync_enabled() is False


def test_config_sync_enabled_invalid_raises_without_echoing(monkeypatch):
    monkeypatch.setattr(config_sync, "repo_env_raw_value", lambda key: "maybe-secret")
    with pytest.raises(ConfigSyncError) as excinfo:
        config_sync_enabled()
    assert "maybe-secret" not in str(excinfo.value)


# --- persona / identity ----------------------------------------------------


def test_shared_core_prompt_is_written_verbatim(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="APPEND OVERRIDE CORE")
    assert sync_maibot_config(instance) is True
    bot = _read_bot(instance)
    assert bot["personality"]["personality"] == "APPEND OVERRIDE CORE"
    assert bot["personality"]["behavior_style"] == "keep behavior"
    assert bot["bot"]["nickname"] == "牛牛"
    assert bot["bot"]["alias_names"] == ["牛牛"]


def test_replace_override_does_not_mix_db_persona(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="REPLACE CORE ONLY")
    assert sync_maibot_config(instance) is True
    assert _read_bot(instance)["personality"]["personality"] == "REPLACE CORE ONLY"


def test_persona_read_is_db_free_in_cold_cli(monkeypatch):
    import importlib

    compile_mod = importlib.import_module("pallas.product.persona.compile_persona_prompt")

    def _boom(*args, **kwargs):
        raise AssertionError("DB repository must not be touched")

    monkeypatch.setattr(compile_mod, "make_bot_config_repository", _boom)
    text = config_sync._load_persona_text()
    assert isinstance(text, str)
    assert text.strip()


def _patch_override_asset(monkeypatch: pytest.MonkeyPatch, asset: Path) -> None:
    import importlib

    bpo = importlib.import_module("pallas.product.persona.base_prompt_override")
    cpp = importlib.import_module("pallas.product.persona.compile_persona_prompt")
    monkeypatch.setattr(bpo, "base_prompt_override_path", lambda: asset)
    cpp.clear_base_system_prompt_cache()


def test_real_global_override_append_replace_applied_in_process(tmp_path, monkeypatch):
    import importlib

    instance = _make_instance(tmp_path)
    compile_mod = importlib.import_module("pallas.product.persona.compile_persona_prompt")
    monkeypatch.setattr(
        compile_mod,
        "make_bot_config_repository",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB touched")),
    )
    asset = tmp_path / "override.json"
    _patch_override_asset(monkeypatch, asset)
    real_load = config_sync.load_base_system_prompt
    _install_source(monkeypatch, patch_persona=False)
    monkeypatch.setattr(config_sync, "load_base_system_prompt", real_load)

    builtin = real_load()
    asset.write_text(json.dumps({"enabled": True, "mode": "append", "text": "APPEND_MARKER"}), encoding="utf-8")
    compile_mod.clear_base_system_prompt_cache()
    assert sync_maibot_config(instance) is True
    assert _read_bot(instance)["personality"]["personality"] == builtin + "\n\nAPPEND_MARKER"

    asset.write_text(json.dumps({"enabled": True, "mode": "replace", "text": "REPLACE_ONLY"}), encoding="utf-8")
    compile_mod.clear_base_system_prompt_cache()
    assert sync_maibot_config(instance) is True
    assert _read_bot(instance)["personality"]["personality"] == "REPLACE_ONLY"


_COLD_SCRIPT = """
import importlib, json, os, sys
from pathlib import Path

asset = Path(os.environ["COLD_ASSET"])
bpo = importlib.import_module("pallas.product.persona.base_prompt_override")
cpp = importlib.import_module("pallas.product.persona.compile_persona_prompt")

import nonebot
try:
    nonebot.get_driver()
    driver_ready = True
except Exception:
    driver_ready = False

bpo.base_prompt_override_path = lambda: asset
cpp.clear_base_system_prompt_cache()
base = cpp.load_base_system_prompt()
asset.write_text(json.dumps({"enabled": True, "mode": "append", "text": "COLD_APPEND"}), encoding="utf-8")
cpp.clear_base_system_prompt_cache()
appended = cpp.load_base_system_prompt()
asset.write_text(json.dumps({"enabled": True, "mode": "replace", "text": "COLD_REPLACE"}), encoding="utf-8")
cpp.clear_base_system_prompt_cache()
replaced = cpp.load_base_system_prompt()
print(json.dumps({
    "driver_ready": driver_ready,
    "base_len": len(base),
    "append_ok": appended == base + "\\n\\nCOLD_APPEND",
    "replace_ok": replaced == "COLD_REPLACE",
}))
"""


def test_cold_subprocess_reads_global_override(tmp_path):
    from pallas.core.foundation.config.repo_settings import repo_root

    asset = tmp_path / "cold_override.json"
    asset.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "COLD_ASSET": str(asset), "PYTHONPATH": str(repo_root())}
    result = subprocess.run(
        [sys.executable, "-c", _COLD_SCRIPT],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["driver_ready"] is False
    assert payload["base_len"] > 0
    assert payload["append_ok"] is True
    assert payload["replace_ok"] is True


# --- llm chat / responses / auth / effort ----------------------------------


def test_chat_completions_maps_to_openai_client(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    provider = _provider_by_name(instance, "pallas-prov-a")
    assert provider["client_type"] == "openai"
    assert provider["auth_type"] == "bearer"
    assert provider["api_key"] == _CHAT_SECRET
    assert provider["base_url"] == "https://api.example.com/v1"
    model = _model_by_name(instance, "pallas-prov-a-gpt-x")
    assert model["model_type"] == "llm"
    assert model["model_identifier"] == "gpt-x"
    assert model["visual"] is False
    assert model["extra_params"]["thinking"] == {"type": "disabled"}
    _assert_references(instance)


def test_responses_provider_maps_to_openai_responses(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    row = _chat_row(request_method="responses", model_effort="")
    endpoint = _endpoint(model_effort="", request_method="responses")
    _install_source(monkeypatch, rows={"prov-a": row}, chains={"llm_chat": [endpoint], "turn_decision": [endpoint]})
    assert sync_maibot_config(instance) is True
    assert _provider_by_name(instance, "pallas-prov-a")["client_type"] == "openai_responses"


def test_no_key_endpoint_uses_auth_none(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    row = _chat_row(api_key="", api_keys=[], api_key_env="")
    endpoint = _endpoint(api_key="", api_keys=())
    _install_source(monkeypatch, rows={"prov-a": row}, chains={"llm_chat": [endpoint], "turn_decision": [endpoint]})
    assert sync_maibot_config(instance) is True
    provider = _provider_by_name(instance, "pallas-prov-a")
    assert provider["auth_type"] == "none"
    assert provider["api_key"] == ""


def test_provider_without_key_falls_back_to_global_api_key(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    row = _chat_row(api_key="", api_keys=[], api_key_env="")
    endpoint = _endpoint(api_key="", api_keys=())
    _install_source(
        monkeypatch,
        rows={"prov-a": row},
        chains={"llm_chat": [endpoint], "turn_decision": [endpoint]},
        legacy=("", "", "sk-global"),
    )
    assert sync_maibot_config(instance) is True
    provider = _provider_by_name(instance, "pallas-prov-a")
    assert provider["auth_type"] == "bearer"
    assert provider["api_key"] == "sk-global"


def test_responses_disable_effort_uses_reasoning_none(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    row = _chat_row(request_method="responses", default_model="deepseek-chat")
    row["models"] = [{"name": "deepseek-chat", "capabilities": ["text"], "model_effort": "disable"}]
    endpoint = _endpoint(model="deepseek-chat", model_effort="disable", request_method="responses")
    _install_source(monkeypatch, rows={"prov-a": row}, chains={"llm_chat": [endpoint], "turn_decision": [endpoint]})
    assert sync_maibot_config(instance) is True
    model = _model_by_name(instance, "pallas-prov-a-deepseek-chat")
    assert model["extra_params"]["reasoning"] == {"effort": "none"}


def test_cpa_provider_forces_stream_mode(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    row = _chat_row(provider_id="cpa")
    endpoint = _endpoint(provider_id="cpa")
    _install_source(monkeypatch, rows={"cpa": row}, chains={"llm_chat": [endpoint], "turn_decision": [endpoint]})
    assert sync_maibot_config(instance) is True
    model = _model_by_name(instance, "pallas-cpa-gpt-x")
    assert model["force_stream_mode"] is True


def test_distinct_effective_models_are_not_merged(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    rows = {
        "prov-a": _chat_row("prov-a", model_effort="disable"),
        "prov-b": _chat_row("prov-b", model_effort="enable"),
    }
    chains = {
        "llm_chat": [_endpoint("prov-a", "gpt-x", model_effort="disable")],
        "turn_decision": [_endpoint("prov-b", "gpt-x", model_effort="enable")],
    }
    _install_source(monkeypatch, rows=rows, chains=chains)
    assert sync_maibot_config(instance) is True
    model = _read_model(instance)
    names = {row["name"] for row in model["models"]}
    assert {"pallas-prov-a-gpt-x", "pallas-prov-b-gpt-x"} <= names
    assert model["model_task_config"]["replyer"]["model_list"] == ["pallas-prov-a-gpt-x"]
    assert model["model_task_config"]["utils"]["model_list"] == ["pallas-prov-b-gpt-x"]
    _assert_references(instance)


def test_supported_multi_candidate_chain_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    before = _snapshot(instance)
    rows = {"prov-a": _chat_row("prov-a"), "prov-b": _chat_row("prov-b")}
    chains = {
        "llm_chat": [_endpoint("prov-a", "gpt-x"), _endpoint("prov-b", "gpt-x")],
        "turn_decision": [_endpoint("prov-a", "gpt-small")],
    }
    _install_source(monkeypatch, rows=rows, chains=chains)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


# --- legacy env fallback ---------------------------------------------------


def test_legacy_env_fallback_used_when_no_providers(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(
        monkeypatch,
        chains={"llm_chat": [], "turn_decision": []},
        legacy=("https://legacy.example.com/v1", "legacy-model", "legacy-key"),
    )
    assert sync_maibot_config(instance) is True
    provider = _provider_by_name(instance, "pallas-legacy")
    assert provider["client_type"] == "openai"
    assert provider["base_url"] == "https://legacy.example.com/v1"
    assert provider["api_key"] == "legacy-key"
    model = _model_by_name(instance, "pallas-legacy-legacy-model")
    assert model["model_identifier"] == "legacy-model"
    assert _read_model(instance)["model_task_config"]["replyer"]["model_list"] == ["pallas-legacy-legacy-model"]
    _assert_references(instance)


def test_no_endpoint_and_no_legacy_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    before = _snapshot(instance)
    _install_source(monkeypatch, chains={"llm_chat": [], "turn_decision": []})
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


# --- embedding -------------------------------------------------------------


def test_embedding_line_written_as_embedding_type(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(
        monkeypatch,
        embedding=("https://embed.example.com/v1", _EMBED_SECRET, "prov-embed", "text-embedding-3-small"),
    )
    assert sync_maibot_config(instance) is True
    model = _read_model(instance)
    embed = _model_by_name(instance, "pallas-embed-prov-embed-text-embedding-3-small")
    assert embed["model_type"] == "embedding"
    assert model["model_task_config"]["embedding"]["model_list"] == [embed["name"]]
    _assert_references(instance)


def test_missing_embedding_config_preserves_target_role(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    assert _read_model(instance)["model_task_config"]["embedding"]["model_list"] == ["manual-embedding"]


def test_image_embedding_role_may_reference_text_embedding(tmp_path, monkeypatch):
    # 上游说明（model_configs.py）：image_embedding 可选择文本或图片嵌入类型
    with_image = _MODEL_TOML + '\n[model_task_config.image_embedding]\nmodel_list = ["manual-embedding"]\n'
    instance = _make_instance(tmp_path, model_toml=with_image)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    assert _read_model(instance)["model_task_config"]["image_embedding"]["model_list"] == ["manual-embedding"]


def test_non_embedding_role_referencing_embedding_rejected(tmp_path, monkeypatch):
    bad = _MODEL_TOML.replace(
        '[model_task_config.vlm]\nmodel_list = ["manual-model"]',
        '[model_task_config.vlm]\nmodel_list = ["manual-embedding"]',
    )
    instance = _make_instance(tmp_path, model_toml=bad)
    before = _snapshot(instance)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_embedding_provider_name_collision_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    before = _snapshot(instance)
    chains = {
        "llm_chat": [_endpoint("embed-main", "gpt-x")],
        "turn_decision": [_endpoint("embed-main", "gpt-x")],
    }
    _install_source(
        monkeypatch,
        rows={"embed-main": _chat_row("embed-main")},
        chains=chains,
        embedding=("https://embed.example.com/v1", _EMBED_SECRET, "main", "text-embedding-3-small"),
    )
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_embedding_provider_same_content_reused(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    shared = "https://shared.example.com/v1"
    row = _chat_row("embed-main", base_url=shared, api_key=_EMBED_SECRET, api_keys=[_EMBED_SECRET])
    endpoint = _endpoint("embed-main", "gpt-x", base_url=shared, api_key=_EMBED_SECRET, api_keys=(_EMBED_SECRET,))
    _install_source(
        monkeypatch,
        rows={"embed-main": row},
        chains={"llm_chat": [endpoint], "turn_decision": [endpoint]},
        embedding=(shared, _EMBED_SECRET, "main", "text-embedding-3-small"),
    )
    assert sync_maibot_config(instance) is True
    assert _provider_by_name(instance, "pallas-embed-main")["base_url"] == shared
    assert _model_by_name(instance, "pallas-embed-main-text-embedding-3-small")["model_type"] == "embedding"


def test_illegal_embedding_role_reference_rejected(tmp_path, monkeypatch):
    bad_model = _MODEL_TOML.replace(
        '[model_task_config.embedding]\nmodel_list = ["manual-embedding"]',
        '[model_task_config.embedding]\nmodel_list = ["manual-model"]',
    )
    instance = _make_instance(tmp_path, model_toml=bad_model)
    before = _snapshot(instance)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_task_config_range_violation_rejected(tmp_path, monkeypatch):
    bad_model = _MODEL_TOML.replace(
        '[model_task_config.vlm]\nmodel_list = ["manual-model"]',
        '[model_task_config.vlm]\nmodel_list = ["manual-model"]\ntemperature = 3.0',
    )
    instance = _make_instance(tmp_path, model_toml=bad_model)
    before = _snapshot(instance)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_broken_structure_rejected_without_attribute_error(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path, model_toml='models = 5\n\n[inner]\nversion = "1.17.24"\n')
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError) as excinfo:
        sync_maibot_config(instance)
    assert "AttributeError" not in str(excinfo.value)


def test_broken_task_table_rejected_without_attribute_error(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path, model_toml='[inner]\nversion = "1.17.24"\n\n[model_task_config]\nreplyer = 5\n')
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError) as excinfo:
        sync_maibot_config(instance)
    assert "AttributeError" not in str(excinfo.value)


def test_unmanaged_gemini_provider_without_base_url_allowed(tmp_path, monkeypatch):
    gemini_block = '[[api_providers]]\nname = "gemini-native"\nclient_type = "gemini"\nauth_type = "none"\n\n'
    gemini = _MODEL_TOML.replace(
        '[[models]]\nname = "manual-model"', gemini_block + '[[models]]\nname = "manual-model"'
    )
    instance = _make_instance(tmp_path, model_toml=gemini)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    assert _provider_by_name(instance, "gemini-native")["client_type"] == "gemini"


# --- rejections: files untouched -------------------------------------------


def _snapshot(instance: Path) -> dict[str, bytes]:
    config = instance / "config"
    return {path.name: path.read_bytes() for path in config.iterdir()}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda chains, rows: (chains, {**rows, "prov-a": _chat_row(daily_tokens_cap=100)}),
        lambda chains, rows: (chains, {**rows, "prov-a": _chat_row(api_keys=["k1", "k2"], api_key="k1")}),
        lambda chains, rows: (chains, {**rows, "prov-a": _chat_row(request_method="anthropic_messages")}),
        lambda chains, rows: ({"llm_chat": chains["llm_chat"], "turn_decision": []}, rows),
    ],
)
def test_rejection_leaves_both_files_untouched(tmp_path, monkeypatch, mutate):
    instance = _make_instance(tmp_path)
    before = _snapshot(instance)
    chains, rows = mutate(_default_chains(), {"prov-a": _chat_row()})
    _install_source(monkeypatch, chains=chains, rows=rows)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_chat_daily_budget_cap_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    before = _snapshot(instance)
    _install_source(monkeypatch, budget=(5, 0))
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_unsupported_fallback_member_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    before = _snapshot(instance)
    rows = {
        "prov-a": _chat_row("prov-a"),
        "prov-b": _chat_row("prov-b", request_method="ollama_chat"),
    }
    chains = {"llm_chat": [_endpoint("prov-a"), _endpoint("prov-b")], "turn_decision": [_endpoint("prov-a")]}
    _install_source(monkeypatch, chains=chains, rows=rows)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_bad_inner_version_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path, model_toml=_MODEL_TOML.replace('version = "1.17.24"', 'version = "1.0.0"'))
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)


def test_invalid_toml_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path, model_toml="this is not toml = = =")
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)


def test_missing_required_file_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    (instance / "config" / MODEL_CONFIG_FILENAME).unlink()
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)


def test_error_messages_do_not_leak_secrets(tmp_path, monkeypatch, capsys):
    instance = _make_instance(tmp_path)
    rows = {"prov-a": _chat_row(api_keys=[_CHAT_SECRET, "second-key"], api_key=_CHAT_SECRET)}
    _install_source(monkeypatch, rows=rows)
    with pytest.raises(ConfigSyncError) as excinfo:
        sync_maibot_config(instance)
    captured = capsys.readouterr()
    assert _CHAT_SECRET not in str(excinfo.value)
    assert _CHAT_SECRET not in captured.out
    assert _CHAT_SECRET not in captured.err


# --- preservation ----------------------------------------------------------


def test_unmanaged_entries_and_comments_preserved(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    model_text = (instance / "config" / MODEL_CONFIG_FILENAME).read_text(encoding="utf-8")
    bot_text = (instance / "config" / BOT_CONFIG_FILENAME).read_text(encoding="utf-8")
    assert "# model config comment" in model_text
    assert "# keep this comment" in bot_text
    model = _read_model(instance)
    assert _model_by_name(instance, "manual-model")["extra_params"] == {"foo": "bar"}
    assert _provider_by_name(instance, "manual-provider")["api_key"] == "manual-key"
    assert model["model_task_config"]["vlm"]["model_list"] == ["manual-model"]
    assert model["model_task_config"]["replyer"]["hard_timeout"] == 111.0
    assert model["model_task_config"]["replyer"]["max_tokens"] == 2048
    assert _read_bot(instance)["bot"]["extra_note"] == "keep-me"
    _assert_references(instance)


# --- permissions / backups / idempotency -----------------------------------


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_first_takeover_backup_and_modes(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    original_bot = (instance / "config" / BOT_CONFIG_FILENAME).read_bytes()
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    backup = instance / "config" / f"{BOT_CONFIG_FILENAME}.pallas-backup"
    assert backup.read_bytes() == original_bot
    assert _mode(backup) == 0o600
    assert _mode(instance / "config" / BOT_CONFIG_FILENAME) == 0o600
    assert _mode(instance / "config" / MODEL_CONFIG_FILENAME) == 0o600
    assert _mode(instance / "config" / config_sync.MARKER_FILENAME) == 0o600


def test_temp_file_written_0600(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    recorded: list[int] = []
    real_replace = Path.replace

    def spy_replace(self, target):
        recorded.append(_mode(self))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", spy_replace)
    assert sync_maibot_config(instance) is True
    assert recorded
    assert all(mode == 0o600 for mode in recorded)


def test_repeat_run_is_byte_identical_and_skips_backup(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    backup = instance / "config" / f"{BOT_CONFIG_FILENAME}.pallas-backup"
    backup_before = backup.read_bytes()
    bot_before = (instance / "config" / BOT_CONFIG_FILENAME).read_bytes()
    model_before = (instance / "config" / MODEL_CONFIG_FILENAME).read_bytes()
    assert sync_maibot_config(instance) is False
    assert backup.read_bytes() == backup_before
    assert (instance / "config" / BOT_CONFIG_FILENAME).read_bytes() == bot_before
    assert (instance / "config" / MODEL_CONFIG_FILENAME).read_bytes() == model_before


def test_source_update_rewrites(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="FIRST CORE")
    assert sync_maibot_config(instance) is True
    monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: "SECOND CORE")
    assert sync_maibot_config(instance) is True
    assert _read_bot(instance)["personality"]["personality"] == "SECOND CORE"


def test_unmanaged_keys_on_managed_rows_survive_source_update(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="FIRST")
    assert sync_maibot_config(instance) is True
    model_path = instance / "config" / MODEL_CONFIG_FILENAME
    text = model_path.read_text(encoding="utf-8")
    text = text.replace(
        'name = "pallas-prov-a-gpt-x"',
        'name = "pallas-prov-a-gpt-x"\nmax_tokens = 123\ntemperature = 0.42',
    )
    text = text.replace(
        'name = "pallas-prov-a"',
        'name = "pallas-prov-a"\ndefault_headers = { X-Trace = "1" }',
    )
    model_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: "SECOND")
    assert sync_maibot_config(instance) is True
    assert _model_by_name(instance, "pallas-prov-a-gpt-x")["max_tokens"] == 123
    assert _model_by_name(instance, "pallas-prov-a-gpt-x")["temperature"] == 0.42
    assert _provider_by_name(instance, "pallas-prov-a")["default_headers"] == {"X-Trace": "1"}
    assert _read_bot(instance)["personality"]["personality"] == "SECOND"


def test_native_task_limits_survive_sync_and_source_updates(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="FIRST")
    assert sync_maibot_config(instance) is True
    assert _read_model(instance)["model_task_config"]["replyer"]["max_tokens"] == 2048
    model_path = instance / "config" / MODEL_CONFIG_FILENAME
    model_path.write_text(
        model_path.read_text(encoding="utf-8").replace("max_tokens = 2048", "max_tokens = 3072"),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: "SECOND")
    assert sync_maibot_config(instance) is True
    assert _read_model(instance)["model_task_config"]["replyer"]["max_tokens"] == 3072
    assert "max_tokens" not in _read_model(instance)["model_task_config"]["planner"]


# --- backup safety ---------------------------------------------------------


def test_existing_backup_same_bytes_reused(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    config_dir = instance / "config"
    original_bot = (config_dir / BOT_CONFIG_FILENAME).read_bytes()
    backup = config_dir / f"{BOT_CONFIG_FILENAME}.pallas-backup"
    backup.write_bytes(original_bot)
    os.chmod(backup, 0o600)
    before = backup.read_bytes()
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    assert backup.read_bytes() == before


def test_existing_backup_unsafe_mode_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    config_dir = instance / "config"
    original_bot = (config_dir / BOT_CONFIG_FILENAME).read_bytes()
    backup = config_dir / f"{BOT_CONFIG_FILENAME}.pallas-backup"
    backup.write_bytes(original_bot)
    os.chmod(backup, 0o644)
    before = _snapshot(instance)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_existing_backup_diff_bytes_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    config_dir = instance / "config"
    (config_dir / f"{BOT_CONFIG_FILENAME}.pallas-backup").write_bytes(b"stale backup")
    before = _snapshot(instance)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_all_backups_checked_before_any_write(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    config_dir = instance / "config"
    real = config_dir / "backup-real.toml"
    real.write_text("x", encoding="utf-8")
    (config_dir / f"{MODEL_CONFIG_FILENAME}.pallas-backup").symlink_to(real)
    before = _snapshot(instance)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    after = _snapshot(instance)
    assert after == before
    assert not (config_dir / f"{BOT_CONFIG_FILENAME}.pallas-backup").exists()


def test_write_survives_absent_post_replace_chmod(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)

    def _boom(self, mode):
        raise AssertionError("no post-replace chmod expected")

    monkeypatch.setattr(Path, "chmod", _boom)
    assert sync_maibot_config(instance) is True


# --- conflict detection ----------------------------------------------------


def test_managed_hand_edit_conflict(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    model_path = instance / "config" / MODEL_CONFIG_FILENAME
    edited = model_path.read_text(encoding="utf-8").replace('model_identifier = "gpt-x"', 'model_identifier = "hacked"')
    model_path.write_text(edited, encoding="utf-8")
    before = _snapshot(instance)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
    assert _snapshot(instance) == before


def test_unmanaged_hand_edit_does_not_conflict(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    model_path = instance / "config" / MODEL_CONFIG_FILENAME
    edited = model_path.read_text(encoding="utf-8").replace('"manual-x"', '"manual-edited"')
    model_path.write_text(edited, encoding="utf-8")
    assert sync_maibot_config(instance) is False
    assert _model_by_name(instance, "manual-model")["model_identifier"] == "manual-edited"


# --- rollback / symlink / dry-run ------------------------------------------


def test_second_write_failure_rolls_back_first(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    before = _snapshot(instance)
    modes_before = {
        BOT_CONFIG_FILENAME: _mode(instance / "config" / BOT_CONFIG_FILENAME),
        MODEL_CONFIG_FILENAME: _mode(instance / "config" / MODEL_CONFIG_FILENAME),
    }
    real_write = config_sync._write_text_0600

    def flaky(path, text):
        if path.name == MODEL_CONFIG_FILENAME:
            raise OSError("simulated failure")
        real_write(path, text)

    monkeypatch.setattr(config_sync, "_write_text_0600", flaky)
    with pytest.raises(OSError, match="simulated failure"):
        sync_maibot_config(instance)
    after = _snapshot(instance)
    assert after[BOT_CONFIG_FILENAME] == before[BOT_CONFIG_FILENAME]
    assert after[MODEL_CONFIG_FILENAME] == before[MODEL_CONFIG_FILENAME]
    assert config_sync.MARKER_FILENAME not in after
    assert _mode(instance / "config" / BOT_CONFIG_FILENAME) == modes_before[BOT_CONFIG_FILENAME]
    assert _mode(instance / "config" / MODEL_CONFIG_FILENAME) == modes_before[MODEL_CONFIG_FILENAME]


def test_symlink_target_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    real = instance / "config" / "real.toml"
    real.write_text(_BOT_TOML, encoding="utf-8")
    link = instance / "config" / BOT_CONFIG_FILENAME
    link.unlink()
    link.symlink_to(real)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)


def test_symlink_marker_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    marker = instance / "config" / config_sync.MARKER_FILENAME
    real = instance / "config" / "marker-real.json"
    real.write_text(marker.read_text(encoding="utf-8"), encoding="utf-8")
    marker.unlink()
    marker.symlink_to(real)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    before = _snapshot(instance)
    assert sync_maibot_config(instance, dry_run=True) is True
    assert _snapshot(instance) == before


def test_failed_rollback_reports_static_error(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="FIRST CORE")
    assert sync_maibot_config(instance) is True
    monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: "SECOND CORE")
    real_bytes = config_sync._write_bytes_0600

    def flaky_text(path, text):
        if path.name == MODEL_CONFIG_FILENAME:
            raise OSError("boom")
        real_bytes(path, text.encode("utf-8"), 0o600)

    def failing_bytes(path, data, mode):
        raise OSError("restore boom")

    monkeypatch.setattr(config_sync, "_write_text_0600", flaky_text)
    monkeypatch.setattr(config_sync, "_write_bytes_0600", failing_bytes)
    with pytest.raises(ConfigSyncError, match="manual recovery"):
        sync_maibot_config(instance)


def test_original_marker_bytes_restored_on_failure(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch, persona="FIRST CORE")
    assert sync_maibot_config(instance) is True
    marker = instance / "config" / config_sync.MARKER_FILENAME
    marker_before = marker.read_bytes()
    monkeypatch.setattr(config_sync, "load_base_system_prompt", lambda: "SECOND CORE")
    real_write = config_sync._write_text_0600

    def flaky(path, text):
        if path.name == MODEL_CONFIG_FILENAME:
            raise OSError("boom")
        real_write(path, text)

    monkeypatch.setattr(config_sync, "_write_text_0600", flaky)
    with pytest.raises(OSError, match="boom"):
        sync_maibot_config(instance)
    assert marker.read_bytes() == marker_before


# --- routing resolver integration ------------------------------------------


def _routing_doc(*, p1_enabled: bool = True) -> dict:
    def row(pid: str, model: str, enabled: bool) -> dict:
        return {
            "id": pid,
            "kind": "remote",
            "base_url": f"https://{pid}.example.com/v1",
            "api_keys": [f"key-{pid}"],
            "api_key_env": "",
            "default_model": model,
            "models": [{"name": model}],
            "enabled": enabled,
            "task_models": {},
            "capabilities": ["text"],
            "model_effort": "",
            "request_method": "chat_completions",
            "daily_tokens_cap": 0,
            "daily_cost_cap": 0.0,
        }

    return {
        "providers": [row("p1", "m1", p1_enabled), row("p2", "m2", True), row("p3", "m3", False)],
        "routing": {
            "tasks": {"llm_chat": "p1"},
            "task_backups": {"llm_chat": "p2"},
            "tier_backups": {},
            "tier_backup_models": {},
            "task_backup_models": {},
            "chain_fallback": ["p3"],
            "cost_currency": "",
        },
    }


def test_task_route_priority_and_disabled(monkeypatch):
    from pallas.product.llm import providers_store

    monkeypatch.setattr(providers_store, "load_providers_document", lambda refresh=False: _routing_doc())
    chain = config_sync._load_task_chain("llm_chat")
    assert [endpoint.provider_id for endpoint in chain] == ["p1", "p2"]

    monkeypatch.setattr(
        providers_store, "load_providers_document", lambda refresh=False: _routing_doc(p1_enabled=False)
    )
    disabled_chain = config_sync._load_task_chain("llm_chat")
    assert [endpoint.provider_id for endpoint in disabled_chain] == ["p2"]


def test_marker_contains_no_secret(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    raw = (instance / "config" / config_sync.MARKER_FILENAME).read_text(encoding="utf-8")
    assert _CHAT_SECRET not in raw
    payload = json.loads(raw)
    assert payload["version"] == config_sync.MARKER_VERSION
    assert "digest" in payload


def test_inner_versions_preserved(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    _install_source(monkeypatch)
    assert sync_maibot_config(instance) is True
    assert _read_bot(instance)["inner"]["version"] == config_sync.BOT_CONFIG_VERSION
    assert _read_model(instance)["inner"]["version"] == config_sync.MODEL_CONFIG_VERSION


def test_visual_flag_comes_from_capability(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    row = _chat_row()
    row["models"] = [{"name": "gpt-x", "capabilities": ["text", "image"], "model_effort": "disable"}]
    endpoint = _endpoint(capabilities=("text", "image"))
    _install_source(monkeypatch, rows={"prov-a": row}, chains={"llm_chat": [endpoint], "turn_decision": [endpoint]})
    assert sync_maibot_config(instance) is True
    assert _model_by_name(instance, "pallas-prov-a-gpt-x")["visual"] is True


def test_unused_unsupported_provider_does_not_block(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    rows = {
        "prov-a": _chat_row("prov-a"),
        "unused": _chat_row("unused", request_method="ollama_chat"),
    }
    _install_source(monkeypatch, rows=rows)
    assert sync_maibot_config(instance) is True


def test_symlink_backup_rejected(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    backup = instance / "config" / f"{BOT_CONFIG_FILENAME}.pallas-backup"
    real = instance / "config" / "backup-real.toml"
    real.write_text("x", encoding="utf-8")
    backup.symlink_to(real)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)


def test_symlink_config_dir_rejected(tmp_path, monkeypatch):
    instance = tmp_path / "instance"
    real_config = tmp_path / "real-config"
    real_config.mkdir(parents=True)
    (real_config / BOT_CONFIG_FILENAME).write_text(_BOT_TOML, encoding="utf-8")
    (real_config / MODEL_CONFIG_FILENAME).write_text(_MODEL_TOML, encoding="utf-8")
    instance.mkdir()
    (instance / "config").symlink_to(real_config)
    _install_source(monkeypatch)
    with pytest.raises(ConfigSyncError):
        sync_maibot_config(instance)
