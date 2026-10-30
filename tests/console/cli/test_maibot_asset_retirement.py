from pathlib import Path

import pytest

from pallas.console.cli import maibot_assets as assets


def test_verified_proxy_is_archived_outside_plugins_without_deleting_user_files(tmp_path):
    assets.deploy_assets(tmp_path)
    target = tmp_path / "plugins" / assets.PLUGIN_DIR_NAME
    original = {path.name: path.read_bytes() for path in target.iterdir()}
    other = tmp_path / "plugins" / "user-plugin"
    other.mkdir()
    (other / "user.py").write_text("keep")

    archived = assets.retire_managed_provider_assets(tmp_path)

    assert archived is not None and archived.is_dir()
    assert archived.is_relative_to(tmp_path)
    assert not archived.is_relative_to(tmp_path / "plugins")
    assert {path.name: path.read_bytes() for path in archived.iterdir()} == original
    assert not target.exists()
    assert (other / "user.py").read_text() == "keep"
    assert assets.retire_managed_provider_assets(tmp_path) is None


@pytest.mark.parametrize("change", ["unknown", "modified", "extra", "symlink"])
def test_retirement_refuses_unverified_proxy_without_changing_it(tmp_path, change):
    assets.deploy_assets(tmp_path)
    target = tmp_path / "plugins" / assets.PLUGIN_DIR_NAME
    if change == "unknown":
        (target / assets.MARKER_NAME).unlink()
    elif change == "modified":
        (target / "plugin.py").write_text("user code")
    elif change == "extra":
        (target / "user.py").write_text("keep")
    else:
        original = tmp_path / "original.py"
        (target / "plugin.py").rename(original)
        (target / "plugin.py").symlink_to(original)
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    with pytest.raises(assets.MaiBotAssetsError):
        assets.retire_managed_provider_assets(tmp_path)
    assert target.is_dir()
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before


def test_retirement_rename_failure_preserves_original_and_reports_failure(tmp_path, monkeypatch):
    assets.deploy_assets(tmp_path)
    target = tmp_path / "plugins" / assets.PLUGIN_DIR_NAME
    original = {path.name: path.read_bytes() for path in target.iterdir()}
    rename = Path.rename

    def fail_retirement(path, destination):
        if path == target:
            raise OSError("synthetic failure")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_retirement)
    with pytest.raises(assets.MaiBotAssetsError, match="归档失败"):
        assets.retire_managed_provider_assets(tmp_path)
    assert {path.name: path.read_bytes() for path in target.iterdir()} == original
    assert not list(tmp_path.glob(".pallas-retired-provider-*"))


def test_absent_proxy_retirement_does_not_create_directories(tmp_path):
    assert assets.retire_managed_provider_assets(tmp_path) is None
    assert list(tmp_path.iterdir()) == []
