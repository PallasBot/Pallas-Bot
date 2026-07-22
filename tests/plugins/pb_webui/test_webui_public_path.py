from pathlib import Path
from unittest.mock import MagicMock

import packages.pb_webui.manager as manager


def test_webui_public_path_vue(monkeypatch) -> None:
    root = Path("/tmp/pb_webui_data_test")
    monkeypatch.setattr(manager, "pb_webui_data_dir", lambda: root)
    cfg = MagicMock(pallas_webui_frontend="vue")
    monkeypatch.setattr(manager, "plugin_config", cfg, raising=False)
    # webui_frontend_stack imports plugin_config from .config
    monkeypatch.setattr(
        "packages.pb_webui.config.plugin_config",
        MagicMock(pallas_webui_frontend="vue"),
    )
    assert manager.webui_frontend_stack() == "vue"
    assert manager.webui_public_path() == root / "public"


def test_webui_public_path_react(monkeypatch) -> None:
    root = Path("/tmp/pb_webui_data_test")
    monkeypatch.setattr(manager, "pb_webui_data_dir", lambda: root)
    monkeypatch.setattr(
        "packages.pb_webui.config.plugin_config",
        MagicMock(pallas_webui_frontend="react"),
    )
    assert manager.webui_frontend_stack() == "react"
    assert manager.webui_public_path() == root / "public-react"
