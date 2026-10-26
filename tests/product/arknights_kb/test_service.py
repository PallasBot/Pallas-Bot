from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pallas.product.arknights_kb import service


def test_query_tool_contract_is_fixed_and_closed() -> None:
    assert set(service.QUERY_TOOLS) == {
        "arknights.operator.get",
        "arknights.operator.search",
        "arknights.skill.get",
        "arknights.enemy.get",
        "arknights.enemy.search",
        "prts.search",
        "prts.read",
        "prts.timeline",
    }
    for name, tool in service.QUERY_TOOLS.items():
        assert tool["scope"] in {"arknights:read", "prts:read"}
        assert tool["parameters"]["type"] == "object"
        assert tool["parameters"]["additionalProperties"] is False
        assert name.startswith("prts.") == (tool["scope"] == "prts:read")


def test_operator_query_uses_domain_query_and_marks_partial_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "source": "fixture",
        "rarity_filter": "TIER_6",
        "operators": [{"id": "char_1", "name": "测试干员", "skills": []}],
    }
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: payload)

    result = service.execute_query("arknights.operator.get", {"name": "测试干员"})

    assert result["ok"] is True
    assert result["result"]["found"] is True
    assert result["result"]["operator"]["name"] == "测试干员"
    assert result["result"]["coverage"]["complete"] is False
    assert result["result"]["coverage"]["coverage_status"] == "partial"


def test_missing_source_is_not_a_not_found_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: None)

    result = service.execute_query("arknights.operator.get", {"name": "不存在"})

    assert result == {"ok": False, "error": "source_unavailable", "result": None}


def test_loaded_source_not_found_is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.domain.arknights.query.load_kb_operators_payload",
        lambda: {"source": "fixture", "rarity_filter": "ALL", "operators": []},
    )

    result = service.execute_query("arknights.operator.get", {"name": "不存在"})

    assert result["ok"] is True
    assert result["result"]["found"] is False
    assert result["result"]["coverage"]["complete"] is True
    assert result["result"]["coverage"]["coverage_status"] == "complete"


def test_operator_coverage_is_unknown_without_completeness_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.domain.arknights.query.load_kb_operators_payload",
        lambda: {"source": "fixture", "operators": []},
    )

    result = service.execute_query("arknights.operator.get", {"name": "不存在"})

    assert result["ok"] is True
    assert result["result"]["coverage"]["complete"] is None
    assert result["result"]["coverage"]["coverage_status"] == "unknown"


def test_enemy_coverage_is_unknown_without_completeness_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.domain.arknights.query.load_enemies_payload",
        lambda: {"source": "fixture", "enemies": []},
    )

    result = service.execute_query("arknights.enemy.get", {"name": "不存在"})

    assert result["ok"] is True
    assert result["result"]["coverage"]["complete"] is None
    assert result["result"]["coverage"]["coverage_status"] == "unknown"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("arknights.operator.get", {}),
        ("arknights.operator.get", {"name": True}),
        ("arknights.operator.get", {"name": "   "}),
        ("arknights.operator.get", {"name": "x" * 81}),
        ("arknights.operator.get", {"name": "测试干员", "other": 1}),
        ("arknights.operator.search", {"query": "x", "limit": True}),
        ("arknights.operator.search", {"query": "x" * 201}),
        ("arknights.skill.get", {"name": "x", "skill_index": True}),
        ("arknights.skill.get", {"name": "x", "skill_index": 4}),
        ("prts.search", {"query": "x", "limit": 11}),
        ("prts.search", {"query": "x" * 201}),
        ("prts.search", {"query": "x", "games": ["arknights"] * 11}),
        ("prts.search", {"query": "x", "resource_types": ["x" * 81]}),
        ("prts.search", {"query": "x", "games": ["../../etc"]}),
        ("prts.read", {"document_uid": "x", "start_line": 1_000_001}),
        ("prts.read", {"document_uid": "x" * 513}),
        ("prts.read", {"document_id": "x" * 513}),
        ("prts.read", {"display_title": "x" * 513}),
        ("prts.read", {"source_ref": "x" * 513}),
        ("prts.read", {"document_uid": "x", "end_line": 1_000_001}),
        ("prts.read", {"document_uid": "x", "max_lines": 201}),
        ("prts.read", {"document_uid": "x", "max_chars": 20_001}),
        ("prts.timeline", {"entity_names": ["孤星"] * 11}),
    ],
)
def test_invalid_arguments_fail_safely(name: str, arguments: dict) -> None:
    result = service.execute_query(name, arguments)

    assert result == {"ok": False, "error": "invalid_arguments", "result": None}


def test_unknown_tool_and_non_object_arguments_fail_safely() -> None:
    assert service.execute_query("not.allowed", {})["error"] == "unknown_tool"
    assert service.execute_query("prts.search", [])["error"] == "invalid_arguments"


def test_query_service_is_disabled_by_global_kb_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: service.ArknightsKbConfig(arknights_kb_enabled=False),
    )

    result = service.execute_query("prts.search", {"query": "孤星"})

    assert result == {"ok": False, "error": "source_disabled", "result": None}


def test_prts_query_obeys_its_own_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: service.ArknightsKbConfig(prts_corpus_enabled=False),
    )

    assert service.execute_query("prts.search", {"query": "孤星"}) == {
        "ok": False,
        "error": "source_disabled",
        "result": None,
    }


def test_prts_not_found_is_success_with_installed_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.arknights_kb import prts_runtime
    from pallas.product.arknights_kb.prts_corpus import CorpusNotFoundError

    class Store:
        def snapshot(self) -> dict:
            return {"release_id": "r1", "data_version": "a" * 64, "packs": ["references"]}

        def status(self, *, pointer=None, pack_ids=None, require_search_index=False) -> dict:
            return {
                "installed": True,
                "release_id": "r1",
                "data_version": "a" * 64,
                "packs": [{"pack_id": "references"}],
            }

        def read(self, **_kwargs) -> dict:
            raise CorpusNotFoundError("private local detail")

    monkeypatch.setattr(service, "get_arknights_kb_config", service.ArknightsKbConfig)
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: Store())

    result = service.execute_query("prts.read", {"document_uid": "missing"})

    assert result["ok"] is True
    assert result["result"]["found"] is False
    assert result["result"]["coverage"]["complete"] is False
    assert result["result"]["coverage"]["packs"] == ["references"]


def test_prts_query_does_not_download_when_source_is_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from pallas.product.arknights_kb import prts_corpus, prts_runtime

    monkeypatch.setattr(service, "get_arknights_kb_config", service.ArknightsKbConfig)
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: prts_corpus.CorpusStore(tmp_path))
    monkeypatch.setattr(
        prts_corpus,
        "_request_json",
        lambda *_args, **_kwargs: pytest.fail("query must not contact the upstream"),
    )

    result = service.execute_query("prts.search", {"query": "孤星"})

    assert result == {"ok": False, "error": "source_unavailable", "result": None}


def test_prts_read_cannot_read_an_installed_but_unconfigured_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.arknights_kb import prts_corpus, prts_runtime

    class Store:
        def snapshot(self) -> dict:
            return {"release_id": "r1", "data_version": "a" * 64, "packs": ["official_game"]}

        def status(self, *, pointer=None, pack_ids=None, require_search_index=False) -> dict:
            return {
                "installed": True,
                "release_id": "r1",
                "data_version": "a" * 64,
                "packs": [
                    {"pack_id": "official_game"},
                    {"pack_id": "endfield_official_game"},
                ],
            }

        def read(self, **kwargs) -> dict:
            allowed_packs = kwargs.get("pack_ids")
            if allowed_packs is None or "endfield_official_game" in allowed_packs:
                return {"title": "终末地资料"}
            raise prts_corpus.CorpusNotFoundError("not in configured scope")

    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: service.ArknightsKbConfig(prts_corpus_packs="official_game"),
    )
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: Store())

    result = service.execute_query("prts.read", {"document_uid": "endfield-document"})

    assert result["ok"] is True
    assert result["result"]["found"] is False
    assert result["result"]["coverage"]["packs"] == ["official_game"]


def test_prts_timeline_requires_references_in_configured_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.arknights_kb import prts_runtime

    class Store:
        def snapshot(self) -> dict:
            return {"release_id": "r1", "data_version": "a" * 64, "packs": ["references"]}

        def status(self, *, pointer=None, pack_ids=None, require_search_index=False) -> dict:
            return {
                "installed": True,
                "release_id": "r1",
                "data_version": "a" * 64,
                "packs": [{"pack_id": "references"}],
            }

        def search(self, *_args, **_kwargs) -> dict:
            pytest.fail("timeline must not search a pack outside the configured scope")

    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: service.ArknightsKbConfig(prts_corpus_packs="official_game"),
    )
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: Store())

    result = service.execute_query("prts.timeline", {"query": "泰拉"})

    assert result == {"ok": False, "error": "source_unavailable", "result": None}


def test_query_result_over_64k_fails_without_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"source": "fixture", "rarity_filter": "ALL", "operators": []}
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: payload)
    monkeypatch.setattr(
        "pallas.core.domain.arknights.query.search_operators",
        lambda *_args, **_kwargs: [{"name": "x" * 70_000}],
    )

    result = service.execute_query("arknights.operator.search", {"query": "x"})

    assert result == {"ok": False, "error": "output_limit_exceeded", "result": None}


def test_bot_tool_handlers_use_shared_query_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.tools import arknights

    calls: list[tuple[str, dict]] = []

    def execute(name: str, arguments: dict) -> dict:
        calls.append((name, arguments))
        return {"ok": True, "error": "", "result": {"found": True, "operator": {"name": "A"}}}

    monkeypatch.setattr(service, "execute_query", execute)
    result = asyncio.run(arknights.handle_operator_get({"name": "A"}))

    assert calls == [("arknights.operator.get", {"name": "A"})]
    assert result == {"ok": True, "error": "", "result": {"found": True, "operator": {"name": "A"}}}


def test_prts_config_fields_match_shared_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.arknights_kb import config

    monkeypatch.setattr(config, "repo_env_raw_value", lambda _key: None)
    cfg = service.get_arknights_kb_config()

    assert cfg.prts_corpus_enabled is True
    assert cfg.prts_corpus_packs == "official_game,reviewed_wiki,terra_journey,entities,references"
    assert cfg.prts_corpus_include_endfield is False
    assert cfg.prts_corpus_search_limit == 5
    assert cfg.prts_corpus_read_max_lines == 80
    assert cfg.prts_corpus_read_max_chars == 12_000
    assert cfg.prts_corpus_download_timeout_sec == 120


def test_query_payload_is_json_serializable() -> None:
    result = service.execute_query("arknights.operator.get", {"name": "缺失来源"})
    json.dumps(result, ensure_ascii=False)


def test_shared_query_service_imports_without_fcntl_or_nonebot_initialization() -> None:
    script = """
import importlib.abc
import nonebot
import sys

sys.modules.pop("fcntl", None)

class BlockFcntl(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "fcntl":
            raise ModuleNotFoundError("fcntl disabled for this test")

sys.meta_path.insert(0, BlockFcntl())
from pallas.product.arknights_kb import service

try:
    nonebot.get_driver()
except ValueError:
    pass
else:
    raise AssertionError("NoneBot unexpectedly initialized")

service.ark_query.load_kb_operators_payload = lambda: {
    "source": "fixture", "rarity_filter": "ALL", "operators": []
}
result = service.execute_query("arknights.operator.get", {"name": "不存在"})
assert result["ok"] is True and result["result"]["found"] is False
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
