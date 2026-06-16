from __future__ import annotations

from src.platform.bot_runtime import plugin_loader


def test_load_discovered_plugin_modules_applies_skip_rules(monkeypatch):
    calls: list[tuple[str, str, set[str]]] = []

    def fake_load(module_path: str, *, role_label: str, loaded_short: set[str]) -> bool:
        calls.append((module_path, role_label, set(loaded_short)))
        loaded_short.add(module_path.rsplit(".", 1)[-1])
        return True

    monkeypatch.setattr(plugin_loader, "_load_plugin_module", fake_load)

    loaded_short = {"already"}
    count = plugin_loader._load_discovered_plugin_modules(
        role_label="worker",
        module_paths=[
            "src.plugins.skip_by_path",
            "src.plugins.keep",
            "src.plugins.skip_me",
            "src.plugins.already",
        ],
        skip_short=frozenset({"skip_me"}),
        skip_module_paths=frozenset({"src.plugins.skip_by_path"}),
        loaded_short=loaded_short,
    )

    assert count == 1
    assert calls == [("src.plugins.keep", "worker", {"already"})]
    assert loaded_short == {"already", "keep"}
