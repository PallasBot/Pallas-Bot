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
        "pallas_protocol_snowluma_linux_use_docker": False,
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


def test_refresh_snowluma_managed_runtime_refs_updates_stale_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    sl_v1 = data / "runtime_extract" / "snowluma" / "v1.0.0"
    sl_v2 = data / "runtime_extract" / "snowluma" / "v2.0.0"
    sl_v1.mkdir(parents=True)
    sl_v2.mkdir(parents=True)
    (sl_v1 / "index.mjs").write_text("//", encoding="utf-8")
    (sl_v2 / "index.mjs").write_text("//", encoding="utf-8")
    mgr = LaunchManager(
        data,
        tmp_path / "resource",
        _cfg(),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
    )
    account = {"program_dir": str(sl_v1), "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND}
    mgr._refresh_snowluma_managed_runtime_refs(account, str(sl_v2))
    assert Path(account["program_dir"]).resolve() == sl_v2.resolve()


def test_apply_defaults_snowluma_linux_docker_allocator_callback(tmp_path: Path) -> None:
    sl_root = tmp_path / "snowluma_dist"
    sl_root.mkdir()
    (sl_root / "index.mjs").write_text("//", encoding="utf-8")

    def alloc(acc: dict) -> dict[str, int]:
        _ = acc
        return {
            "onebot_http": 18110,
            "onebot_ws": 18111,
            "host_novnc": 23220,
            "host_vnc": 23221,
        }

    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(
            pallas_protocol_linux_use_docker=True,
            pallas_protocol_snowluma_program_dir=str(sl_root),
            pallas_protocol_webui_port_min=6200,
            pallas_protocol_webui_port_max=6300,
        ),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
        runtime_profile_provider=lambda: {"runtime_mode": "docker"},
        snowluma_docker_allocate_host_ports=alloc,
    )
    account = {
        "id": "10007",
        "qq": "10007",
        "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND,
        "webui_port": 6250,
    }
    with patch("src.plugins.pallas_protocol.launch_manager.sys.platform", "linux"):
        mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account.get("snowluma_linux_docker") is True
    assert account["snowluma_docker_host_onebot_http"] == 18110
    assert account["snowluma_docker_host_onebot_ws"] == 18111
    assert account["snowluma_docker_host_novnc_port"] == 23220
    assert account["snowluma_docker_host_vnc_port"] == 23221


def test_apply_defaults_snowluma_docker_when_profile_sl_docker_even_if_napcat_shell(tmp_path: Path) -> None:
    sl_root = tmp_path / "snowluma_dist2"
    sl_root.mkdir()
    (sl_root / "index.mjs").write_text("//", encoding="utf-8")

    def alloc(acc: dict) -> dict[str, int]:
        _ = acc
        return {"onebot_http": 18112, "onebot_ws": 18113, "host_novnc": 23230, "host_vnc": 23231}

    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(
            pallas_protocol_linux_use_docker=False,
            pallas_protocol_snowluma_linux_use_docker=False,
            pallas_protocol_snowluma_program_dir=str(sl_root),
            pallas_protocol_webui_port_min=6200,
            pallas_protocol_webui_port_max=6300,
        ),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
        runtime_profile_provider=lambda: {
            "napcat_runtime_mode": "shell",
            "snowluma_runtime_mode": "docker",
            "runtime_mode": "shell",
        },
        snowluma_docker_allocate_host_ports=alloc,
    )
    account = {
        "id": "10009",
        "qq": "10009",
        "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND,
        "webui_port": 6251,
    }
    with patch("src.plugins.pallas_protocol.launch_manager.sys.platform", "linux"):
        mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account.get("snowluma_linux_docker") is True


def test_apply_defaults_snowluma_linux_docker_default_ports_match_upstream(tmp_path: Path) -> None:
    sl_root = tmp_path / "snowluma_dist"
    sl_root.mkdir()
    (sl_root / "index.mjs").write_text("//", encoding="utf-8")
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(
            pallas_protocol_linux_use_docker=True,
            pallas_protocol_snowluma_program_dir=str(sl_root),
            pallas_protocol_webui_port_min=6200,
            pallas_protocol_webui_port_max=6300,
        ),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
        runtime_profile_provider=lambda: {"runtime_mode": "docker"},
    )
    account = {
        "id": "10007",
        "qq": "10007",
        "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND,
        "webui_port": 6250,
    }
    with patch("src.plugins.pallas_protocol.launch_manager.sys.platform", "linux"):
        mgr.apply_defaults(account, lambda a: str(a.get("qq", "")))
    assert account.get("snowluma_linux_docker") is True
    assert account["snowluma_docker_host_onebot_http"] == 3000
    assert account["snowluma_docker_host_onebot_ws"] == 3001
    assert account["snowluma_docker_host_novnc_port"] == 6081
    assert account["snowluma_docker_host_vnc_port"] == 5900


def test_refresh_snowluma_managed_runtime_refs_skips_custom_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    sl_v2 = data / "runtime_extract" / "snowluma" / "v2.0.0"
    sl_v2.mkdir(parents=True)
    (sl_v2 / "index.mjs").write_text("//", encoding="utf-8")
    custom = tmp_path / "my_sl"
    custom.mkdir()
    (custom / "index.mjs").write_text("//", encoding="utf-8")
    mgr = LaunchManager(
        data,
        tmp_path / "resource",
        _cfg(),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
    )
    account = {"program_dir": str(custom), "protocol_backend": SNOWLUMA_PROTOCOL_BACKEND}
    mgr._refresh_snowluma_managed_runtime_refs(account, str(sl_v2))
    assert account["program_dir"] == str(custom)


def test_prepare_dirs_rewrites_docker_marker_working_dir(tmp_path: Path) -> None:
    ad = tmp_path / "inst" / "acc1"
    ad.mkdir(parents=True)
    mgr = LaunchManager(
        tmp_path / "data",
        tmp_path / "resource",
        _cfg(),
        instances_root=tmp_path / "instances",
        platform=PosixNapcatPlatform(),
    )
    account = {"working_dir": "docker:mlikiowa/napcat-docker:latest", "account_data_dir": str(ad)}
    mgr.prepare_dirs(account)
    assert account["working_dir"].replace("\\", "/") == str(ad).replace("\\", "/")
    assert ad.is_dir()
