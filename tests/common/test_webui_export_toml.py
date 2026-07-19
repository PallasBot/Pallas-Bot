import json
from pathlib import Path

import pytest

from pallas.core.foundation.config import webui_export_toml as wet
from pallas.core.foundation.config.repo_settings import upsert_repo_settings_items


def test_rebuild_sections_groups_known_plugin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    wet.clear_env_key_section_cache()
    index = wet.env_key_to_section_label()
    assert "ANSWER_THRESHOLD" in index
    assert index["ANSWER_THRESHOLD"].startswith("plugin.")

    sections = wet.rebuild_webui_json_sections({"ANSWER_THRESHOLD": "2", "UNKNOWN_KEY_XYZ": "1"})
    assert "other" in sections
    assert sections[index["ANSWER_THRESHOLD"]]["ANSWER_THRESHOLD"] == "2"


def test_upsert_writes_sections_and_export_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui = tmp_path / "webui.json"
    export_path = tmp_path / "export.toml"
    monkeypatch.setattr("pallas.core.foundation.config.repo_settings.repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(wet, "repo_webui_export_toml_path", lambda: export_path)
    wet.clear_env_key_section_cache()

    upsert_repo_settings_items({"ANSWER_THRESHOLD": "3"})
    data = json.loads(webui.read_text(encoding="utf-8"))
    assert data["env"]["ANSWER_THRESHOLD"] == "3"
    assert isinstance(data.get("sections"), dict)
    assert export_path.is_file()
    text = export_path.read_text(encoding="utf-8")
    assert "请勿手动编辑" in text
    assert "[webui." in text
    assert "ANSWER_THRESHOLD" in text


def test_export_toml_tolerates_malformed_sections_bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui = tmp_path / "webui.json"
    export_path = tmp_path / "export.toml"
    webui.write_text(
        json.dumps(
            {
                "env": {"FOO": "1", "BAR": "2"},
                "sections": {"bad": "not-a-dict", "good": {"foo": "1"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(wet, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(wet, "repo_webui_export_toml_path", lambda: export_path)

    wet.export_webui_inspection_toml()

    assert export_path.is_file()
    text = export_path.read_text(encoding="utf-8")
    assert "FOO" in text or "BAR" in text
