from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from pallas.core.platform.ai_callback.media_task_hooks import (
    clear_media_task_hooks_for_tests,
    invoke_media_task_failure,
    invoke_media_task_success,
    register_media_task_hooks,
)


@pytest.fixture(autouse=True)
def reset_hooks():
    clear_media_task_hooks_for_tests()
    yield
    clear_media_task_hooks_for_tests()


def test_register_and_invoke_media_task_hooks() -> None:
    seen: list[str] = []

    register_media_task_hooks(
        "draw",
        on_failure=lambda task: seen.append(f"fail:{task['id']}"),
        on_success=lambda task, blob, gid: seen.append(f"ok:{task['id']}:{gid}:{len(blob)}"),
    )

    assert invoke_media_task_failure({"task_type": "draw", "id": "a"}) is True
    assert (
        invoke_media_task_success(
            {"task_type": "draw", "id": "b"},
            image_bytes=b"\x89PNG" + b"x" * 64,
            group_id=123,
        )
        is True
    )
    assert seen == ["fail:a", "ok:b:123:68"]
    assert invoke_media_task_failure({"task_type": "other"}) is False


def test_import_plugin_submodule_prefers_loaded_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.plugin_runtime import resolve as resolve_mod

    fake_mod = ModuleType("local.plugins.draw.runtime_state")
    fake_mod.record_ai_runtime_failure = MagicMock()

    plugin = MagicMock()
    plugin.name = "draw"
    plugin.module = ModuleType("local.plugins.draw")
    plugin.module.__name__ = "local.plugins.draw"

    monkeypatch.setattr(resolve_mod, "get_loaded_plugins", lambda: [plugin])
    monkeypatch.setitem(sys.modules, "local.plugins.draw.runtime_state", fake_mod)

    loaded = resolve_mod.import_plugin_submodule("draw", "runtime_state")
    assert loaded is fake_mod
