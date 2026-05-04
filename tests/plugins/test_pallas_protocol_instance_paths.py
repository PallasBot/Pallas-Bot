"""instances/<id>/<协议段>/ 与旧版 instances/<id>/ 兼容。"""

from pathlib import Path

from src.plugins.pallas_protocol.contract import (
    normalize_instance_folder_segment,
    resolve_default_account_data_dir,
)


def test_normalize_instance_folder_segment() -> None:
    assert normalize_instance_folder_segment("napcat") == "napcat"
    assert normalize_instance_folder_segment("NapCat") == "napcat"
    assert normalize_instance_folder_segment("snow-luma") == "snow-luma"
    assert normalize_instance_folder_segment("") == "napcat"
    assert normalize_instance_folder_segment("a/b") == "a-b"


def test_resolve_prefers_new_layout_when_exists(tmp_path: Path) -> None:
    ir = tmp_path / "instances"
    nested = ir / "10001" / "napcat"
    nested.mkdir(parents=True)
    (nested / "config").mkdir()
    r = resolve_default_account_data_dir(ir, "10001", "napcat")
    assert r == nested.resolve()


def test_resolve_falls_back_to_legacy_napcat_layout(tmp_path: Path) -> None:
    ir = tmp_path / "instances"
    legacy = ir / "10002"
    legacy.mkdir(parents=True)
    (legacy / "config").mkdir()
    r = resolve_default_account_data_dir(ir, "10002", "napcat")
    assert r == legacy.resolve()


def test_resolve_new_layout_when_no_disk_yet(tmp_path: Path) -> None:
    ir = tmp_path / "instances"
    r = resolve_default_account_data_dir(ir, "10003", "napcat")
    assert r == (ir / "10003" / "napcat").resolve()
    assert not r.exists()


def test_resolve_legacy_without_config_uses_nested(tmp_path: Path) -> None:
    """无 config/ 的旧目录不视为有效存量，走新布局。"""
    ir = tmp_path / "instances"
    legacy = ir / "10004"
    legacy.mkdir(parents=True)
    (legacy / "tmp.txt").write_text("x", encoding="utf-8")
    r = resolve_default_account_data_dir(ir, "10004", "napcat")
    assert r == (ir / "10004" / "napcat").resolve()
