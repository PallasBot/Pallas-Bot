from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.platform.plugin_runtime.resolve import audit_plugin_submodule_targets

if TYPE_CHECKING:
    import pytest


def test_audit_plugin_submodule_targets_reports_registry_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.plugin_runtime.resolve.importlib.util.find_spec",
        lambda name: object() if name in {"pallas_plugin_relogin_bot", "pallas_plugin_bot_status"} else None,
    )

    rows = audit_plugin_submodule_targets(["relogin_bot", "bot_status"])

    assert rows == [
        {
            "plugin_id": "relogin_bot",
            "module_prefix": "pallas_plugin_relogin_bot",
            "ok": True,
        },
        {
            "plugin_id": "bot_status",
            "module_prefix": "pallas_plugin_bot_status",
            "ok": True,
        },
    ]
