from __future__ import annotations

import importlib

import pytest

from pallas.product.persona import base_prompt_override as overrides
from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.compile_persona_prompt import (
    compile_persona_prompt,
    load_at_chat_system_prompt,
    load_base_system_prompt,
)


@pytest.fixture
def override_asset(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> object:
    path = tmp_path / "base_prompt_override.json"
    monkeypatch.setattr(overrides, "base_prompt_override_path", lambda: path)
    return path


def test_append_override_keeps_new_builtin_base(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(overrides, "base_prompt_override_path", lambda: tmp_path / "base.json")
    overrides.save_base_prompt_override(mode="append", text="用户规则", builtin_text="新版基线")
    assert overrides.resolve_base_prompt(builtin_text="新版基线") == "新版基线\n\n用户规则"


def test_replace_override_does_not_absorb_builtin_update(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(overrides, "base_prompt_override_path", lambda: tmp_path / "base.json")
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="旧版基线")
    assert overrides.resolve_base_prompt(builtin_text="新版基线") == "用户完整基线"


def test_missing_asset_resolves_to_builtin(override_asset) -> None:
    assert overrides.resolve_base_prompt(builtin_text="基线") == "基线"


def test_disabled_override_resolves_to_builtin(override_asset) -> None:
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="基线")
    overrides.set_base_prompt_override_enabled(enabled=False)
    assert overrides.resolve_base_prompt(builtin_text="新版基线") == "新版基线"
    assert overrides.base_prompt_override_status()["enabled"] is False


def test_save_status_shape(override_asset) -> None:
    overrides.save_base_prompt_override(mode="append", text="用户规则", builtin_text="基线")
    status = overrides.base_prompt_override_status()
    assert status["enabled"] is True
    assert status["mode"] == "append"
    assert status["text"] == "用户规则"
    assert status["builtin_sha256"]
    assert status["updated_at"]
    assert len(status["versions"]) == 1
    assert status["versions"][0]["text"] == "用户规则"


def test_save_keeps_up_to_ten_history_versions(override_asset) -> None:
    for i in range(12):
        overrides.save_base_prompt_override(mode="append", text=f"规则{i}", builtin_text="基线")
    status = overrides.base_prompt_override_status()
    assert len(status["versions"]) == 10
    assert status["text"] == "规则11"
    assert status["versions"][0]["text"] == "规则11"


def test_restore_returns_history_version(override_asset) -> None:
    overrides.save_base_prompt_override(mode="append", text="第一版", builtin_text="基线")
    first_id = overrides.base_prompt_override_status()["versions"][0]["id"]
    overrides.save_base_prompt_override(mode="replace", text="第二版", builtin_text="基线")
    overrides.restore_base_prompt_override(version_id=first_id)
    status = overrides.base_prompt_override_status()
    assert status["text"] == "第一版"
    assert status["mode"] == "append"


def test_restore_unknown_version_raises(override_asset) -> None:
    overrides.save_base_prompt_override(mode="append", text="第一版", builtin_text="基线")
    with pytest.raises(KeyError):
        overrides.restore_base_prompt_override(version_id="missing")


def test_status_reports_builtin_updated(monkeypatch, tmp_path, override_asset) -> None:
    builtin_file = tmp_path / "builtin.txt"
    builtin_file.write_text("旧版基线", encoding="utf-8")
    compile_mod = importlib.import_module("pallas.product.persona.compile_persona_prompt")
    monkeypatch.setattr(compile_mod, "resolve_base_system_prompt_path", lambda: builtin_file)
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="旧版基线")
    assert overrides.base_prompt_override_status()["builtin_updated"] is False
    builtin_file.write_text("新版基线", encoding="utf-8")
    assert overrides.base_prompt_override_status()["builtin_updated"] is True


def test_builtin_sha256_anchored_to_builtin_file_not_callers_text(monkeypatch, tmp_path, override_asset) -> None:
    builtin_file = tmp_path / "builtin.txt"
    builtin_file.write_text("内置A", encoding="utf-8")
    compile_mod = importlib.import_module("pallas.product.persona.compile_persona_prompt")
    monkeypatch.setattr(compile_mod, "resolve_base_system_prompt_path", lambda: builtin_file)
    overrides.save_base_prompt_override(mode="replace", text="用户", builtin_text="外部基线")
    assert overrides.base_prompt_override_status()["builtin_updated"] is False
    builtin_file.write_text("内置B", encoding="utf-8")
    assert overrides.base_prompt_override_status()["builtin_updated"] is True


def test_clear_removes_asset(override_asset) -> None:
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="基线")
    overrides.clear_base_prompt_override()
    assert not override_asset.exists()
    assert overrides.resolve_base_prompt(builtin_text="基线") == "基线"


def test_load_base_system_prompt_appends_override(override_asset) -> None:
    overrides.save_base_prompt_override(mode="append", text="用户规则", builtin_text="")
    text = load_base_system_prompt()
    assert "帕拉斯" in text
    assert text.endswith("\n\n用户规则")


def test_load_base_system_prompt_replaces_override(override_asset) -> None:
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="")
    assert load_base_system_prompt() == "用户完整基线"


def test_at_chat_prompt_not_affected_by_override(override_asset) -> None:
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="")
    assert "你是女性，名为帕拉斯" in load_at_chat_system_prompt()


def test_external_file_applies_override_when_enabled(override_asset, tmp_path) -> None:
    external = tmp_path / "external_base.txt"
    external.write_text("外部基线", encoding="utf-8")
    overrides.save_base_prompt_override(mode="append", text="用户规则", builtin_text="")
    assert load_base_system_prompt(custom_path=str(external)) == "外部基线\n\n用户规则"


def test_external_file_verbatim_when_override_disabled(override_asset, tmp_path) -> None:
    external = tmp_path / "external_base.txt"
    external.write_text("外部基线", encoding="utf-8")
    overrides.save_base_prompt_override(mode="append", text="用户规则", builtin_text="")
    overrides.set_base_prompt_override_enabled(enabled=False)
    assert load_base_system_prompt(custom_path=str(external)) == "外部基线"


def test_compile_persona_prompt_uses_override_when_base_system_not_given(override_asset) -> None:
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="")
    bundle = compile_persona_prompt(derive_persona_from_bot_id(1), None, bot_id=1)
    assert "用户完整基线" in bundle.sections.base


def test_explicit_base_system_takes_priority_over_override(override_asset) -> None:
    overrides.save_base_prompt_override(mode="replace", text="用户完整基线", builtin_text="")
    bundle = compile_persona_prompt(
        derive_persona_from_bot_id(1),
        None,
        bot_id=1,
        base_system="显式基线",
    )
    assert "显式基线" in bundle.sections.base
    assert "用户完整基线" not in bundle.sections.base
