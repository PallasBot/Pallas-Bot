from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING

import pytest

from packages.pb_webui import bot_release_bundle
from packages.pb_webui.bot_release_bundle import (
    ReleaseBundleError,
    apply_release_bundle,
    install_docker_release_bundle,
    safe_extract_release_bundle,
)

if TYPE_CHECKING:
    from pathlib import Path


def write_bundle(
    path: Path,
    *,
    tag: str = "v4.2.0",
    extra_members: list[tarfile.TarInfo] | None = None,
) -> None:
    root = f"pallas-bot-{tag}"
    files = {
        f"{root}/pyproject.toml": b"[project]\nname='pallas-bot'\n",
        f"{root}/uv.lock": b"lock",
        f"{root}/pallas/__init__.py": b"VERSION = 'new'\n",
        f"{root}/packages/pb_core/__init__.py": b"NEW = True\n",
        f"{root}/config/pallas.example.toml": b"[bootstrap]\n",
        f"{root}/config/pallas.toml": b"must-not-apply",
        f"{root}/resource/styles/default/style.css": b"new",
        f"{root}/resource/voices/user.wav": b"must-not-apply",
        f"{root}/data/pb_webui/public-react/index.html": b"must-not-apply",
        f"{root}/local/plugins/site.py": b"must-not-apply",
        f"{root}/bot.py": b"print('new')\n",
        f"{root}/.git/config": b"must-not-apply",
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        for member in extra_members or []:
            archive.addfile(member, io.BytesIO(b"x") if member.size else None)


def test_safe_extract_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    bad = tarfile.TarInfo("pallas-bot-v4.2.0/../../escape")
    bad.size = 1
    write_bundle(archive, extra_members=[bad])

    with pytest.raises(ReleaseBundleError, match="越界"):
        safe_extract_release_bundle(archive, tmp_path / "stage", expected_tag="v4.2.0")


def test_safe_extract_rejects_links(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    link = tarfile.TarInfo("pallas-bot-v4.2.0/pallas/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    write_bundle(archive, extra_members=[link])

    with pytest.raises(ReleaseBundleError, match="链接"):
        safe_extract_release_bundle(archive, tmp_path / "stage", expected_tag="v4.2.0")


def test_safe_extract_requires_matching_single_root(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    write_bundle(archive, tag="v4.1.0")

    with pytest.raises(ReleaseBundleError, match="版本"):
        safe_extract_release_bundle(archive, tmp_path / "stage", expected_tag="v4.2.0")


def test_apply_replaces_code_and_preserves_mounted_content(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    stage = tmp_path / "stage"
    target = tmp_path / "app"
    write_bundle(archive)
    bundle = safe_extract_release_bundle(archive, stage, expected_tag="v4.2.0")
    (target / "pallas").mkdir(parents=True)
    (target / "pallas" / "old.py").write_text("old", encoding="utf-8")
    (target / "config").mkdir()
    (target / "config" / "pallas.toml").write_text("secret", encoding="utf-8")
    (target / "resource" / "voices").mkdir(parents=True)
    (target / "resource" / "voices" / "user.wav").write_bytes(b"user")
    (target / "data").mkdir()
    (target / "data" / "state.json").write_text("state", encoding="utf-8")
    (target / "local" / "plugins").mkdir(parents=True)
    (target / "local" / "plugins" / "site.py").write_text("site", encoding="utf-8")

    result = apply_release_bundle(bundle, target)

    assert result["tag"] == "v4.2.0"
    assert not (target / "pallas" / "old.py").exists()
    assert (target / "pallas" / "__init__.py").read_text(encoding="utf-8") == "VERSION = 'new'\n"
    assert (target / "config" / "pallas.toml").read_text(encoding="utf-8") == "secret"
    assert (target / "config" / "pallas.example.toml").is_file()
    assert (target / "resource" / "voices" / "user.wav").read_bytes() == b"user"
    assert (target / "resource" / "styles" / "default" / "style.css").read_bytes() == b"new"
    assert (target / "data" / "state.json").read_text(encoding="utf-8") == "state"
    assert (target / "local" / "plugins" / "site.py").read_text(encoding="utf-8") == "site"
    assert not (target / ".git").exists()


@pytest.mark.asyncio
async def test_install_downloads_validates_and_applies_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_archive = tmp_path / "source.tar.gz"
    target = tmp_path / "app"
    write_bundle(source_archive)
    progress: list[tuple[int, str]] = []

    async def resolve_urls(*_args, **_kwargs) -> list[str]:
        return ["https://example.test/pallas-bot-v4.2.0.tar.gz"]

    def download(_url: str, destination: Path, **_kwargs) -> int:
        destination.write_bytes(source_archive.read_bytes())
        return destination.stat().st_size

    async def run_inline(function, /, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(bot_release_bundle, "resolve_github_release_asset_urls", resolve_urls)
    monkeypatch.setattr(bot_release_bundle, "sync_stream_download_to_file", download)
    monkeypatch.setattr(bot_release_bundle.asyncio, "to_thread", run_inline)

    def record_progress(percent: int, message: str) -> None:
        progress.append((percent, message))

    result = await install_docker_release_bundle(
        target_root=target,
        repo="PallasBot/Pallas-Bot",
        tag="v4.2.0",
        on_progress=record_progress,
    )

    assert result["tag"] == "v4.2.0"
    assert (target / "pallas" / "__init__.py").is_file()
    assert [message for _, message in progress] == [
        "解析 Release 下载地址…",
        "下载 Release 部署包…",
        "校验并解压 Release 部署包…",
        "应用 Release 程序文件…",
    ]
