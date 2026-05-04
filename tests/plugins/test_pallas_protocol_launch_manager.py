from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.plugins.pallas_protocol.contract import SNOWLUMA_PROTOCOL_BACKEND
from src.plugins.pallas_protocol.launch_manager import LaunchManager
from src.plugins.pallas_protocol.platform.posix import PosixNapcatPlatform


def _cfg(**kwargs):
    base = {
        "pallas_protocol_default_command": "node",
        "pallas_protocol_default_args": ["napcat.mjs"],
        "pallas_protocol_program_dir": "",
        "pallas_protocol_snowluma_program_dir": "",
        "pallas_protocol_linux_use_docker": False,
        "pallas_protocol_docker_internal_webui_port": 6099,
        "pallas_protocol_docker_image": "mlikiowa/napcat-docker:latest",
        "pallas_protocol_linux_use_xvfb": True,
        "pallas_protocol_linux_xvfb_command": "xvfb-run",
        "pallas_protocol_linux_xvfb_args": ["--auto-servernum"],
        "pallas_protocol_linux_appimage_args": ["--appimage-extract-and-run"],
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_apply_defaults_linux_wraps_with_xvfb_when_non_docker(tmp_path: Path) -> None:
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
    )
    account = {"id": "10001", "qq": "10001"}
    with patch("src.plugins.pallas_protocol.launch_manager.sys.platform", "linux"):
        mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account["command"] == "xvfb-run"
    assert account["args"] == [
        "--auto-servernum",
        "node",
        str(Path(account["program_dir"]) / "napcat.mjs"),
        "-q",
        "10001",
    ]
    assert account.get("napcat_linux_docker") is False


def test_apply_defaults_linux_docker_mode_keeps_docker_command(tmp_path: Path) -> None:
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(pallas_protocol_linux_use_docker=True),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
    )
    account = {"id": "10002", "qq": "10002"}
    with (
        patch("src.plugins.pallas_protocol.launch_manager.sys.platform", "linux"),
        patch("src.plugins.pallas_protocol.linux_docker.is_linux", return_value=True),
    ):
        mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account["command"] == "docker"
    assert account.get("napcat_linux_docker") is True


def test_apply_defaults_snowluma_sets_program_and_entry(tmp_path: Path) -> None:
    sl_root = tmp_path / "snowluma_dist"
    sl_root.mkdir()
    (sl_root / "index.mjs").write_text("//", encoding="utf-8")
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(pallas_protocol_snowluma_program_dir=str(sl_root)),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
    )
    account = {
        "id": "10005",
        "qq": "10005",
        "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND,
    }
    mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account["program_dir"] == str(sl_root)
    assert str(sl_root / "index.mjs") in account["args"][0]
    assert "snowluma" in account["account_data_dir"].replace("\\", "/")


def test_apply_defaults_snowluma_prefers_runtime_store_over_resource(tmp_path: Path) -> None:
    sl_root = tmp_path / "data" / "runtime_extract" / "snowluma" / "pkg"
    sl_root.mkdir(parents=True)
    (sl_root / "index.mjs").write_text("//", encoding="utf-8")
    res = tmp_path / "resource" / "snowluma"
    res.mkdir(parents=True)
    (res / "index.mjs").write_text("old", encoding="utf-8")
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(pallas_protocol_snowluma_program_dir=""),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
        snowluma_runtime_dir_provider=lambda: sl_root,
    )
    account = {
        "id": "10006",
        "qq": "10006",
        "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND,
    }
    mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account["program_dir"] == str(sl_root)


def test_apply_defaults_linux_prefers_appimage_then_xvfb(tmp_path: Path) -> None:
    runtime_file = tmp_path / "runtime" / "QQ-x86_64.AppImage"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(b"ELF")
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(),
        instances_root=tmp_path / "instances",
        runtime_dir_provider=lambda: runtime_file,
        platform=PosixNapcatPlatform(),
    )
    account = {"id": "10003", "qq": "10003"}
    with patch("src.plugins.pallas_protocol.launch_manager.sys.platform", "linux"):
        mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account["command"] == "xvfb-run"
    assert account["args"] == ["--auto-servernum", str(runtime_file), "--appimage-extract-and-run", "-q", "10003"]
