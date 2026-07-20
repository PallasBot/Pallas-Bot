"""store-assets 须在 warm 任务写盘前挂载，避免 SPA catch-all 吞掉插件封面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui.config import Config
from packages.pb_webui.public import register_routes

if TYPE_CHECKING:
    from pathlib import Path


def test_register_routes_mounts_store_assets_before_dir_exists(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "pb_webui"
    data_root.mkdir()
    public_dir = data_root / "public"
    public_dir.mkdir()
    (public_dir / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")

    store_assets = data_root / "store-assets"
    assert not store_assets.exists()

    monkeypatch.setattr("packages.pb_webui.public.pb_webui_data_dir", lambda *, create=True: data_root)

    app = FastAPI()
    register_routes(
        app,
        public_dir=public_dir,
        base="/pallas",
        plugin_config=Config(pallas_webui_dev_mode=True),
    )

    assert store_assets.is_dir()
    cover = store_assets / "cover"
    cover.mkdir()
    png = cover / "official-demo.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-png-body")

    client = TestClient(app)
    response = client.get("/pallas/store-assets/cover/official-demo.png")

    assert response.status_code == 200
    assert response.content == png.read_bytes()
    assert "text/html" not in (response.headers.get("content-type") or "")
