from __future__ import annotations

import json

import pytest

from pallas.console.webui.community_plugin_author import validate_index_file


def _index(plugins=None, **overrides):
    return {
        "version": 1,
        "plugins": plugins
        if plugins is not None
        else [
            {
                "id": "example",
                "repository": "https://github.com/example/plugin",
                "ref": "main",
                "icon": "https://example.test/icon.png",
            },
        ],
        **overrides,
    }


def test_validate_index_accepts_valid_current_entries(tmp_path):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(_index()), encoding="utf-8")

    _meta, plugins, issues = validate_index_file(path)

    assert len(plugins) == 1
    assert plugins[0]["plugin_id"] == "example"
    assert plugins[0]["repository_url"] == "https://github.com/example/plugin"
    assert "id" not in plugins[0]
    assert issues == []


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "根对象"),
        ({"version": 2, "plugins": []}, "version"),
        ({"version": True, "plugins": []}, "version"),
        ({"version": 1, "plugins": {}}, "plugins"),
        (_index([None]), r"plugins\[0\]"),
        (_index([{"id": "Bad", "repository": "https://example.test/repo"}]), "id"),
        (
            _index([
                {"id": "same", "repository": "https://example.test/a"},
                {"id": "same", "repository": "https://example.test/b"},
            ]),
            "重复",
        ),
        (_index([{"id": "repo", "repository": "file:///repo"}]), "repository"),
        (_index([{"id": "ref", "repository": "https://example.test/repo", "ref": " "}]), "ref"),
        (_index([{"id": "version", "repository": "https://example.test/repo", "version": "not-semver"}]), "version"),
    ],
)
def test_validate_index_rejects_contract_violations(tmp_path, raw, message):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_index_file(path)


def test_validate_index_cli_returns_nonzero_with_location(tmp_path, capsys):
    from tools.community_plugin_author import cmd_validate_index

    path = tmp_path / "index.json"
    path.write_text(json.dumps(_index([None])), encoding="utf-8")
    args = type("Args", (), {"path": str(path)})()

    assert cmd_validate_index(args) == 1
    assert "plugins[0]" in capsys.readouterr().err


def test_index_entry_command_remains_a_single_entry_draft():
    from pallas.console.webui.community_plugin_author import build_index_entry

    assert (
        build_index_entry(
            plugin_id="example",
            name="Example",
            description="",
            repository="https://github.com/example/plugin",
        )["id"]
        == "example"
    )
