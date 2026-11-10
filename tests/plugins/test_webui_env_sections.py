import importlib.util
import json
import os
from pathlib import Path

import pytest

_MS_CFG = Path(__file__).resolve().parents[2] / "pallas" / "product" / "message_scrub" / "config.py"
skip_no_message_scrub = pytest.mark.skipif(not _MS_CFG.is_file(), reason="无 message_scrub 配置模块")

_GATEWAY_PLUGIN_MODULES = ("pallas_plugin_draw", "pallas_plugin_maa", "pallas_plugin_sing")
_MISSING_GATEWAY_PLUGIN_MODULES = tuple(
    name for name in _GATEWAY_PLUGIN_MODULES if importlib.util.find_spec(name) is None
)
skip_missing_gateway_plugins = pytest.mark.skipif(
    bool(_MISSING_GATEWAY_PLUGIN_MODULES),
    reason=f"缺少可选插件: {', '.join(_MISSING_GATEWAY_PLUGIN_MODULES)}",
)

_REMOVED_COMMON_CONFIG_SECTIONS = frozenset({
    "cmd_perm",
    "command_limits",
    "pb_webui",
    "pb_protocol",
    "help",
    "community_stats",
    "repeater_learn",
    "mail",
    "message_scrub",
    "ingress_fanout",
    "ingress_dispatch",
    "control_plane",
    "corpus_federation",
})


def test_list_webui_env_sections_is_empty():
    from pallas.console.webui import list_webui_env_sections, webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert rows == []
    data = webui_env_section_payload("llm")
    env_keys = {f["env_key"] for f in data["fields"]}
    assert "LLM_CHAT_ENABLED" in env_keys
    assert "CHAT_ENABLE" in env_keys
    assert "LLM_REPEATER_MODE" not in env_keys
    assert "LLM_REPEATER_FEEDBACK_ENABLED" in env_keys
    assert "LLM_REPEATER_GROUP_COOLDOWN_SEC" not in env_keys
    assert "LLM_REPEATER_STRONG_COOLDOWN_SEC" not in env_keys
    assert "LLM_REPEATER_STRONG_ATTEMPT_RATE" not in env_keys
    assert "LLM_REPEATER_MAX_INFLIGHT" not in env_keys
    assert "LLM_REPEATER_GLOBAL_RPM" not in env_keys
    assert "LLM_OUTPUT_FILTER_POLISH_LITE_HARD_PHRASES" not in env_keys
    assert "LLM_OUTPUT_FILTER_POLISH_LITE_SOFT_PHRASES" not in env_keys
    assert "LLM_CHAT_CHAR_BUDGET" in env_keys
    assert "LLM_SESSION_USER_WINDOW" in env_keys
    assert "LLM_MEMORY_RAG_TOP_K" in env_keys
    assert "LLM_MEMORY_AUTO_EPISODE_COOLDOWN_SEC" in env_keys
    assert "LLM_SESSION_SUMMARY_ENABLED" in env_keys
    assert "LLM_BUBBLE_DELAY_BASE_SEC" in env_keys
    assert "LLM_BUBBLE_DELAY_PER_CHAR" in env_keys
    assert "LLM_BUBBLE_DELAY_JITTER" in env_keys
    # Provider 事实源已迁出 WebUI llm 段；运行时/密钥不在本表单
    assert "LLM_RUNTIME" not in env_keys
    assert "LLM_BASE_URL" not in env_keys
    assert "LLM_API_KEY" not in env_keys
    assert "LLM_MODEL" not in env_keys
    assert "LLM_REPEATER_BIAS_ENABLED" in env_keys
    assert "CONVERSATION_FEATURE_LEVEL" in env_keys
    assert "LLM_VECTOR_RETRIEVE" in env_keys
    assert "LLM_EMBEDDING_MODEL" in env_keys
    assert "LLM_OUTPUT_FILTER_ENABLED" in env_keys
    assert "LLM_OUTPUT_FILTER_CHAT_HARD_PHRASES" in env_keys


def test_ingress_dispatch_section_payload_has_field_groups():
    from pallas.console.webui import webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    data = webui_env_section_payload("ingress_dispatch")
    assert data["plugin"] == "ingress_dispatch"
    groups = data.get("field_groups") or []
    assert len(groups) >= 4
    field_names = {f["name"] for f in data["fields"]}
    assert "matcher_dispatch_enabled" in field_names
    assert "send_queue_enabled" in field_names
    assert "gate_queue_warn_ms" in field_names
    assert "gate_queue_warn_ms" in next(group["field_names"] for group in groups if group["id"] == "gate_queue")
    assert "send_queue_max_depth" not in field_names


def test_conversation_scheduler_fields_require_restart() -> None:
    from pallas.console.webui.env_sections import _INGRESS_DISPATCH_SKIP

    assert {
        "conversation_scheduler_enabled",
        "conversation_scheduler_concurrency",
        "conversation_scheduler_max_pending",
    } <= _INGRESS_DISPATCH_SKIP


def test_passive_pool_config_fields_exist() -> None:
    from pallas.core.platform.ingress.dispatch_runtime_config import IngressDispatchRuntimeConfig

    for field in (
        "passive_repeater_concurrency",
        "passive_llm_concurrency",
    ):
        assert field in IngressDispatchRuntimeConfig.model_fields


def test_passive_pool_fields_require_restart() -> None:
    from pallas.console.webui.env_sections import _INGRESS_DISPATCH_SKIP

    assert {
        "passive_repeater_concurrency",
        "passive_llm_concurrency",
    } <= _INGRESS_DISPATCH_SKIP


@skip_no_message_scrub
def test_message_scrub_not_in_common_config_list(monkeypatch: pytest.MonkeyPatch):
    from pallas.console.webui import list_webui_env_sections
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    ids = {r["id"] for r in rows}
    assert "message_scrub" not in ids
    clear_webui_env_sections_cache()


def test_list_webui_env_sections_excludes_plugin_migrated_sections():
    from pallas.console.webui import list_webui_env_sections
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert rows == []
    ids = {r["id"] for r in rows}
    assert _REMOVED_COMMON_CONFIG_SECTIONS.isdisjoint(ids)


def test_removed_common_config_sections_are_unknown():
    from pallas.console.webui.env_sections import get_webui_env_section

    for section_id in _REMOVED_COMMON_CONFIG_SECTIONS:
        with pytest.raises(ValueError, match="pb_core|未知 common-config"):
            get_webui_env_section(section_id)


@skip_missing_gateway_plugins
def test_service_gateways_payload_shape():
    from pallas.console.webui import webui_env_section_payload

    data = webui_env_section_payload("service_gateways")
    assert data["plugin"] == "service_gateways"
    assert data.get("gateway_editor") is True
    assert data.get("supports_connectivity_check") is True
    groups = data.get("field_groups") or []
    assert {g["id"] for g in groups} == {"draw", "maa", "sing"}
    names = {f["name"] for f in data["fields"]}
    assert "pallas_image_base_url" in names
    assert "maa_public_base_url" in names
    assert "sing_enable" in names


def test_arknights_kb_payload_does_not_import_unrelated_special_sections(
    monkeypatch: pytest.MonkeyPatch,
):
    import builtins

    from pallas.console.webui import webui_env_section_payload

    real_import = builtins.__import__

    def guarded_import(name, globals_=None, locals_=None, fromlist=(), level=0):
        if name == "pallas.console.webui.community_stats_section":
            raise AssertionError("arknights_kb payload should not import community_stats_section")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    data = webui_env_section_payload("arknights_kb")
    assert data["plugin"] == "arknights_kb"
    env_keys = {f["env_key"] for f in data["fields"]}
    assert "ARKNIGHTS_KB_ENABLED" in env_keys
    assert "ARKNIGHTS_KB_AUTO_SYNC" in env_keys


def test_field_to_env_uppercase_keys_matches_plugin_api():
    from packages.pb_webui.config import Config
    from pallas.console.webui import field_to_env_uppercase_keys

    m = field_to_env_uppercase_keys(Config)
    assert m["pallas_webui_enabled"] == "PALLAS_WEBUI_ENABLED"


def test_llm_sticker_vision_fields_map_to_runtime_env():
    from pallas.console.webui.env_sections import _llm_section

    section = _llm_section()
    assert section.field_to_env["llm_sticker_vision_enabled"] == "LLM_STICKER_VISION_ENABLED"
    assert section.field_to_env["llm_sticker_vision_max_per_hour"] == "LLM_STICKER_VISION_MAX_PER_HOUR"


def test_mail_patch_roundtrip_via_internal_section(tmp_path, monkeypatch):
    import json

    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.core.foundation.config import repo_settings as rs

    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("mail", {"smtp_server": "smtp.example.com"})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["PALLAS_SMTP_SERVER"] == "smtp.example.com"


def test_common_config_raw_unsupported_section():
    import pytest

    from pallas.console.webui.env_sections import webui_env_section_raw_toml

    with pytest.raises(ValueError, match="不支持"):
        webui_env_section_raw_toml("service_gateways")


@skip_no_message_scrub
def test_message_scrub_payload_shape(monkeypatch: pytest.MonkeyPatch):
    from pallas.console.webui import webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    data = webui_env_section_payload("message_scrub")
    assert data["plugin"] == "message_scrub"
    assert data["module"]
    names = {f["name"] for f in data["fields"]}
    assert "inbound_filter_substrings" in names
    assert "scrub_review_providers_key_present" not in names
    for f in data["fields"]:
        assert f["env_key"]
        assert f["kind"] in ("bool", "int", "float", "json", "string")
    clear_webui_env_sections_cache()


@skip_no_message_scrub
def test_message_scrub_patch_roundtrip(tmp_path, monkeypatch):
    import json

    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache
    from pallas.core.foundation.config import repo_settings as rs

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("message_scrub", {"inbound_filter_substrings": "a,b"})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["PALLAS_INBOUND_FILTER_SUBSTRINGS"] == "a,b"
    clear_webui_env_sections_cache()


def test_log_level_section_payload_shape():
    from pallas.console.webui import webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    data = webui_env_section_payload("log_level")
    assert data["plugin"] == "log_level"
    assert data["module"] == "pallas.core.foundation.log_level_config"
    fields = {f["name"]: f for f in data["fields"]}
    field = fields["log_level"]
    assert field["env_key"] == "LOG_LEVEL"
    assert field["kind"] == "enum"
    assert "TRACE" in field["choices"]
    assert "INFO" in field["choices"]
    clear_webui_env_sections_cache()


def test_log_level_patch_roundtrip(tmp_path, monkeypatch):
    import json

    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache
    from pallas.core.foundation.config import repo_settings as rs

    clear_webui_env_sections_cache()
    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("log_level", {"log_level": "DEBUG"})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["LOG_LEVEL"] == "DEBUG"
    clear_webui_env_sections_cache()


# control_plane / corpus_federation / service_gateways 走专用 payload/patch，message_scrub 视运行开关注册，
# 均不套用通用段覆盖约束。
_GENERIC_SECTION_BUILDERS = (
    ("llm", "_llm_section"),
    ("arknights_kb", "_arknights_kb_section"),
    ("ingress_dispatch", "_ingress_dispatch_section"),
    ("ingress_fanout", "_ingress_fanout_section"),
    ("mail", "_mail_section"),
    ("command_start", "_command_start_section"),
    ("log_level", "_log_level_section"),
)


_GENERIC_SECTION_IDS = [sid for sid, _attr in _GENERIC_SECTION_BUILDERS]


def _generic_section(attr: str):
    from pallas.console.webui import env_sections

    return getattr(env_sections, attr)()


@pytest.mark.parametrize(
    ("section_id", "attr"),
    _GENERIC_SECTION_BUILDERS,
    ids=_GENERIC_SECTION_IDS,
)
def test_section_field_mapping_covers_model(section_id: str, attr: str) -> None:
    """通用段字段必须显式二选一：映射到 env，或列入 skip_fields。"""
    section = _generic_section(attr)
    model_fields = set(section.model_cls.model_fields)
    mapped = set(section.field_to_env)
    skipped = set(section.skip_fields)
    assert section.id == section_id
    assert mapped <= model_fields, f"{section_id} 映射了模型不存在的字段: {sorted(mapped - model_fields)}"
    assert skipped <= model_fields, f"{section_id} 跳过了模型不存在的字段: {sorted(skipped - model_fields)}"
    uncovered = sorted(model_fields - mapped - skipped)
    assert not uncovered, f"{section_id} 字段既未映射也未声明跳过: {uncovered}"


@pytest.mark.parametrize(
    ("section_id", "attr"),
    _GENERIC_SECTION_BUILDERS,
    ids=_GENERIC_SECTION_IDS,
)
def test_exposed_section_fields_have_chinese_label_and_help(section_id: str, attr: str) -> None:
    from pallas.console.webui.field_labels import webui_field_label

    section = _generic_section(attr)
    missing: list[str] = []
    for key in sorted(set(section.field_to_env) - set(section.skip_fields)):
        field = section.model_cls.model_fields[key]
        if not webui_field_label(key) or not str(field.description or "").strip():
            missing.append(key)
    assert not missing, f"{section_id} 缺中文名或说明: {missing}"


def test_llm_section_maps_memory_graph_and_affinity_fields() -> None:
    from pallas.console.webui.env_sections import _llm_section

    section = _llm_section()
    expected = {
        "llm_memory_graph_extract_enabled": "LLM_MEMORY_GRAPH_EXTRACT_ENABLED",
        "llm_memory_graph_extract_on_write": "LLM_MEMORY_GRAPH_EXTRACT_ON_WRITE",
        "llm_memory_graph_extract_daily_budget": "LLM_MEMORY_GRAPH_EXTRACT_DAILY_BUDGET",
        "llm_memory_hiergraph_max_layers": "LLM_MEMORY_HIERGRAPH_MAX_LAYERS",
        "llm_relationship_affinity_enabled": "LLM_RELATIONSHIP_AFFINITY_ENABLED",
        "llm_relationship_affinity_silence_max_penalty": "LLM_RELATIONSHIP_AFFINITY_SILENCE_MAX_PENALTY",
    }
    for key, env_key in expected.items():
        assert section.field_to_env.get(key) == env_key


def test_llm_section_does_not_map_fields_outside_webui_model() -> None:
    from pallas.console.webui.env_sections import _llm_section

    section = _llm_section()
    for stale in (
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        "llm_knowledge_file_ingest_enabled",
        "llm_memory_auto_person_facts_enabled",
    ):
        assert stale not in section.field_to_env
        assert stale not in section.skip_fields


@pytest.fixture
def isolated_webui_settings(tmp_path, monkeypatch):
    """把配置读写与导出都截到 tmp，且清掉进程内可能存在的密钥类环境变量。"""
    from pallas.core.foundation.config import repo_settings as rs
    from pallas.core.foundation.config import webui_export_toml
    from pallas.product.llm.config import clear_llm_config_cache

    baseline = dict(os.environ)
    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "pallas.toml")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(rs, "_load_legacy_dotenv_upper", dict)
    monkeypatch.setattr(webui_export_toml, "repo_webui_export_toml_path", lambda: tmp_path / "export.toml")
    for key in list(os.environ):
        if key.upper().startswith(("LLM_", "TAVILY_", "WEB_SEARCH_")):
            monkeypatch.delenv(key, raising=False)
    rs.clear_merged_repo_settings_cache()
    clear_llm_config_cache()
    yield webui_file
    monkeypatch.undo()
    os.environ.clear()
    os.environ.update(baseline)
    rs.clear_merged_repo_settings_cache()
    clear_llm_config_cache()


def test_llm_memory_ops_patch_roundtrip(isolated_webui_settings) -> None:
    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.product.llm.ops_config import memory_ops_patch_dict

    patch = memory_ops_patch_dict({
        "llm_memory_graph_extract_enabled": False,
        "llm_relationship_affinity_silence_max_penalty": 12,
    })
    payload = apply_webui_env_section_patch("llm", patch)

    stored = json.loads(isolated_webui_settings.read_text(encoding="utf-8"))["env"]
    assert stored["LLM_MEMORY_GRAPH_EXTRACT_ENABLED"] == "false"
    assert stored["LLM_RELATIONSHIP_AFFINITY_SILENCE_MAX_PENALTY"] == "12"

    fields = {f["name"]: f for f in payload["fields"]}
    assert fields["llm_memory_graph_extract_enabled"]["current"] is False
    assert fields["llm_relationship_affinity_silence_max_penalty"]["current"] == 12
