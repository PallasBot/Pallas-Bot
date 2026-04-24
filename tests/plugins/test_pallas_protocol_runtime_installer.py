import zipfile
from pathlib import Path
from unittest.mock import patch

from src.plugins.pallas_protocol.runtime.installer import (
    _github_release_asset_url,
    _safe_extract_zip,
    asset_is_windows_onekey,
    default_release_asset_for_platform,
    find_napcat_program_dir,
    find_onekey_post_install_program_dir,
    resolve_program_dir_under_extract,
)


def test_github_release_asset_url_latest() -> None:
    u = _github_release_asset_url("NapNeko/NapCatQQ", "NapCat.Shell.zip", "")
    assert u.endswith("/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.zip")


def test_github_release_asset_url_tagged() -> None:
    u = _github_release_asset_url("NapNeko/NapCatQQ", "NapCat.Shell.zip", "v1.2.3")
    assert "releases/download/v1.2.3/NapCat.Shell.zip" in u


def test_safe_extract_zip_rejects_zip_slip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    try:
        _safe_extract_zip(bad, tmp_path / "out")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_find_napcat_program_dir(tmp_path: Path) -> None:
    root = tmp_path / "tree" / "a" / "b"
    root.mkdir(parents=True)
    (root / "napcat.mjs").write_text("//", encoding="utf-8")
    found = find_napcat_program_dir(tmp_path / "tree")
    assert found == root


def test_find_shell_prefers_napcat_mjs_over_shallow_exe(tmp_path: Path) -> None:
    """标准 Shell：同层 bootmain 仅有 exe，兄弟目录有 napcat.mjs 时应选 mjs 目录。"""
    root = tmp_path / "extract"
    boot = root / "bootmain"
    shell = root / "NapCat.Test.Shell"
    boot.mkdir(parents=True)
    shell.mkdir(parents=True)
    (boot / "NapCatWinBootMain.exe").write_bytes(b"MZ")
    (shell / "napcat.mjs").write_text("//", encoding="utf-8")
    found = find_napcat_program_dir(root, prefer_bootmain=False)
    assert found == shell


def test_find_onekey_post_install_prefers_shell_bootmain(tmp_path: Path) -> None:
    """一键包安装完成后：根级 bootmain 与 NapCat.*.Shell/bootmain 并存时，应选后者。"""
    root = tmp_path / "extract"
    root_boot = root / "bootmain"
    shell = root / "NapCat.Test.Shell"
    shell_boot = shell / "bootmain"
    root_boot.mkdir(parents=True)
    shell.mkdir(parents=True)
    shell_boot.mkdir(parents=True)
    (root_boot / "NapCatWinBootMain.exe").write_bytes(b"MZ")
    (shell_boot / "NapCatWinBootMain.exe").write_bytes(b"MZ")
    (shell / "napcat.mjs").write_text("//", encoding="utf-8")
    found = find_onekey_post_install_program_dir(root)
    assert found == shell_boot


def test_resolve_onekey_skips_root_bootmain_when_installer_present(tmp_path: Path) -> None:
    """存在 NapCatInstaller.exe 时未完成 Shell 布局，不得把根级 bootmain 当作 program_dir。"""
    root = tmp_path / "e"
    boot = root / "bootmain"
    boot.mkdir(parents=True)
    (boot / "NapCatWinBootMain.exe").write_bytes(b"MZ")
    (root / "NapCatInstaller.exe").write_bytes(b"MZ")
    assert resolve_program_dir_under_extract(root, onekey=True) is None


def test_resolve_onekey_without_installer_falls_back_to_bootmain(tmp_path: Path) -> None:
    """无安装器的一键布局（旧包或测试）仍可从浅层 bootmain 解析。"""
    root = tmp_path / "e"
    boot = root / "bootmain"
    boot.mkdir(parents=True)
    (boot / "NapCatWinBootMain.exe").write_bytes(b"MZ")
    assert resolve_program_dir_under_extract(root, onekey=True) == boot


def test_asset_is_windows_onekey() -> None:
    assert asset_is_windows_onekey("NapCat.Shell.Windows.OneKey.zip") is True
    assert asset_is_windows_onekey("NapCat.Shell.zip") is False


def test_default_release_asset_for_platform() -> None:
    with patch("src.plugins.pallas_protocol.runtime.installer.sys.platform", "win32"):
        assert default_release_asset_for_platform() == "NapCat.Shell.Windows.OneKey.zip"
    for plat in ("linux", "linux2", "darwin", "freebsd15"):
        with patch("src.plugins.pallas_protocol.runtime.installer.sys.platform", plat):
            assert default_release_asset_for_platform() == "NapCat.Shell.zip", plat
