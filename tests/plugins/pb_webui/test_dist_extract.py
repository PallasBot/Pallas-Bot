"""WebUI dist.zip 解压路径解析。"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

from packages.pb_webui.manager import _resolved_extract_root

if TYPE_CHECKING:
    from pathlib import Path


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
