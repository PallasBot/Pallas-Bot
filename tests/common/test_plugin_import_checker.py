from __future__ import annotations

import ast

from tools.check_plugin_imports import (
    FORBIDDEN_PREFIXES_PACKAGES,
    FORBIDDEN_PREFIXES_PACKAGES_STRICT,
    check_file,
    is_forbidden_module,
    module_names_from_import,
)


def test_src_import_forms_are_forbidden_but_boundary_is_respected():
    assert is_forbidden_module("src", ("src",))
    assert is_forbidden_module("src.foo", ("src",))
    assert is_forbidden_module("srcish", ("src",)) is False
    assert is_forbidden_module("srcish.foo", ("src",)) is False

    for statement in ("import src", "import src.foo", "from src.foo import thing"):
        module = module_names_from_import(ast.parse(statement).body[0])[0]
        assert is_forbidden_module(module, FORBIDDEN_PREFIXES_PACKAGES)


def test_strict_package_import_prefixes_keep_api_allowed():
    assert is_forbidden_module("pallas.core.commands", FORBIDDEN_PREFIXES_PACKAGES_STRICT)
    assert is_forbidden_module("pallas.api.commands", FORBIDDEN_PREFIXES_PACKAGES_STRICT) is False
    assert is_forbidden_module("pallas.core.commands.extra", FORBIDDEN_PREFIXES_PACKAGES_STRICT)


def test_check_file_applies_local_and_builtin_strict_package_rules(tmp_path, monkeypatch):
    import tools.check_plugin_imports as checker

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    path = tmp_path / "plugin.py"
    path.write_text("import pallas.api.commands\nimport pallas.core.commands\nimport src.foo\n", encoding="utf-8")

    strict_errors = check_file(path, scope="packages", strict_packages=True)
    local_errors = check_file(path, scope="local", strict_packages=False)

    assert any("pallas.core.commands" in error for error in strict_errors)
    assert not any("pallas.api.commands" in error for error in strict_errors)
    assert any("src.foo" in error for error in strict_errors)
    assert any("pallas.core.commands" in error for error in local_errors)
    assert not any("pallas.api.commands" in error for error in local_errors)
    assert any("src.foo" in error for error in local_errors)
