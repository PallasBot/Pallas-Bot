from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI

import packages.pb_webui.file_manager_api as mod
from packages.pb_webui.file_manager_api import register_file_manager_router


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", root)
    monkeypatch.setattr(mod, "check_pallas_write_token", lambda *args, **kwargs: None)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "b.json").write_text('{"k": 1}', encoding="utf-8")

    app = FastAPI()
    router = APIRouter()
    register_file_manager_router(router, x="/pallas/api", plugin_config=None)
    app.include_router(router)

    from fastapi.testclient import TestClient

    return TestClient(app)


def test_allowed_path_rejects_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", root)
    with pytest.raises(Exception, match="超出允许范围"):
        mod._allowed_path(str(tmp_path / "outside"))


def test_validate_name_rejects_dangerous_names() -> None:
    for name in ("", ".", "..", "a/b", "a\\b", "a\x00b", 'a"b', "a<b"):
        with pytest.raises(Exception, match="文件名"):
            mod._validate_name(name)
    mod._validate_name("正常名字.txt")


def test_list_root(client) -> None:
    response = client.get("/pallas/api/files/list")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["path"] == ""
    names = {entry["name"] for entry in payload["entries"]}
    assert names == {"a.txt", "data"}


def test_list_nested_dir(client) -> None:
    response = client.get("/pallas/api/files/list", params={"path": "data"})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["path"] == "data"
    assert payload["entries"][0]["name"] == "b.json"


def test_read_text_file(client) -> None:
    response = client.get("/pallas/api/files/read", params={"path": "a.txt"})
    assert response.status_code == 200
    assert response.json()["data"]["content"] == "hello"


def test_read_binary_file_rejected(client, tmp_path: Path) -> None:
    (Path(mod.PROJECT_ROOT) / "bin.dat").write_bytes(b"\x00\x01")
    response = client.get("/pallas/api/files/read", params={"path": "bin.dat"})
    assert response.status_code == 400


def test_read_oversize_rejected(client, tmp_path: Path) -> None:
    (Path(mod.PROJECT_ROOT) / "big.txt").write_bytes(b"x" * (mod._MAX_TEXT_BYTES + 1))
    response = client.get("/pallas/api/files/read", params={"path": "big.txt"})
    assert response.status_code == 413


def test_write_saves_content(client) -> None:
    response = client.post("/pallas/api/files/write", json={"path": "a.txt", "content": "updated"})
    assert response.status_code == 200
    assert (Path(mod.PROJECT_ROOT) / "a.txt").read_text(encoding="utf-8") == "updated"


def test_write_requires_write_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny(*args, **kwargs):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="denied")

    monkeypatch.setattr(mod, "check_pallas_write_token", _deny)
    response = client.post("/pallas/api/files/write", json={"path": "a.txt", "content": "x"})
    assert response.status_code == 401


def test_create_file_and_dir(client) -> None:
    assert client.post(
        "/pallas/api/files/create", json={"parent": "", "name": "new.txt"}
    ).status_code == 200
    assert client.post(
        "/pallas/api/files/create", json={"parent": "", "name": "newdir", "is_dir": True}
    ).status_code == 200
    assert (Path(mod.PROJECT_ROOT) / "new.txt").is_file()
    assert (Path(mod.PROJECT_ROOT) / "newdir").is_dir()


def test_rename(client) -> None:
    response = client.post("/pallas/api/files/rename", json={"path": "a.txt", "new_name": "renamed.txt"})
    assert response.status_code == 200
    assert (Path(mod.PROJECT_ROOT) / "renamed.txt").is_file()
    assert not (Path(mod.PROJECT_ROOT) / "a.txt").exists()


def test_delete_file(client) -> None:
    response = client.post("/pallas/api/files/delete", json={"path": "a.txt"})
    assert response.status_code == 200
    assert not (Path(mod.PROJECT_ROOT) / "a.txt").exists()


def test_delete_rejects_root(client) -> None:
    response = client.post("/pallas/api/files/delete", json={"path": ""})
    assert response.status_code == 400


def test_upload(client) -> None:
    response = client.post(
        "/pallas/api/files/upload",
        params={"path": "data"},
        files={"file": ("up.txt", b"uploaded", "text/plain")},
    )
    assert response.status_code == 200
    assert (Path(mod.PROJECT_ROOT) / "data" / "up.txt").read_bytes() == b"uploaded"


def test_download(client) -> None:
    response = client.get("/pallas/api/files/download", params={"path": "a.txt"})
    assert response.status_code == 200
    assert response.content == b"hello"
