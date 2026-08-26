"""WebUI dist.zip 解压路径解析。"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from packages.pb_webui.manager import (
    _resolved_extract_root,
    extract_bundled_webui_dist,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_resolved_extract_root_prefers_public_react(tmp_path: Path) -> None:
    archive = tmp_path / "extracted"
    public_react = archive / "public-react"
    public_react.mkdir(parents=True)
    (public_react / "index.html").write_text("<html>react</html>", encoding="utf-8")
    public = archive / "public"
    public.mkdir(parents=True)
    (public / "index.html").write_text("<html>vue</html>", encoding="utf-8")

    assert _resolved_extract_root(archive) == public_react


def test_resolved_extract_root_prefers_public_subdir(tmp_path: Path) -> None:
    archive = tmp_path / "extracted"
    public = archive / "public"
    public.mkdir(parents=True)
    (public / "index.html").write_text("<html></html>", encoding="utf-8")

    assert _resolved_extract_root(archive) == public


def test_resolved_extract_root_flat_dist(tmp_path: Path) -> None:
    archive = tmp_path / "extracted"
    archive.mkdir()
    (archive / "index.html").write_text("<html></html>", encoding="utf-8")

    assert _resolved_extract_root(archive) == archive


def test_sync_extract_public_zip_layout(tmp_path: Path) -> None:
    from packages.pb_webui.manager import _sync_extract_dist_zip_file

    zip_path = tmp_path / "dist.zip"
    stage = tmp_path / "stage"
    public_src = stage / "public"
    public_src.mkdir(parents=True)
    (public_src / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in public_src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(stage).as_posix())

    dest = tmp_path / "data" / "pb_webui" / "public"
    _sync_extract_dist_zip_file(zip_path, dest)

    assert (dest / "index.html").read_text(encoding="utf-8") == "<html>ok</html>"


async def test_extract_bundled_webui_dist_installs_archive(tmp_path: Path) -> None:
    zip_path = tmp_path / "dist.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("public-react/index.html", "<html>bundled</html>")

    dest = tmp_path / "data" / "pb_webui" / "public-react"

    assert await extract_bundled_webui_dist(dest, zip_path) is True
    assert (dest / "index.html").read_text(encoding="utf-8") == "<html>bundled</html>"


async def test_extract_bundled_webui_dist_checks_compatibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from packages.pb_webui import manager

    zip_path = tmp_path / "dist.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("public-react/index.html", "<html>bundled</html>")
        zf.writestr("public-react/release-manifest.json", "{}")

    validator = AsyncMock()
    monkeypatch.setattr(manager, "validate_webui_dist_archive", validator)

    dest = tmp_path / "data" / "pb_webui" / "public-react"

    assert await manager.extract_bundled_webui_dist(
        dest,
        zip_path,
        token="token",
        current_commit="f" * 40,
        require_compatible_manifest=True,
    ) is True
    validator.assert_awaited_once_with(
        zip_path,
        token="token",
        current_commit="f" * 40,
    )


async def test_extract_bundled_webui_dist_rejects_invalid_archive(tmp_path: Path) -> None:
    zip_path = tmp_path / "dist.zip"
    zip_path.write_text("not a zip", encoding="utf-8")

    assert await extract_bundled_webui_dist(tmp_path / "public-react", zip_path) is False


async def test_download_dist_can_require_compatible_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from packages.pb_webui import manager

    download = MagicMock()
    extract = MagicMock()
    validate = AsyncMock()
    monkeypatch.setattr(manager, "_sync_download_webui_zip", download)
    monkeypatch.setattr(manager, "_sync_extract_dist_zip_file", extract)
    monkeypatch.setattr(manager, "validate_webui_dist_archive", validate)

    result = await manager.download_and_extract_dist_zip(
        tmp_path / "public-react",
        "https://example.test/dist.zip",
        require_compatible_manifest=True,
        github_token="token",
        current_commit="f" * 40,
    )

    assert result is True
    validate.assert_awaited_once()
    assert validate.await_args.kwargs == {"token": "token", "current_commit": "f" * 40}
    extract.assert_called_once()
