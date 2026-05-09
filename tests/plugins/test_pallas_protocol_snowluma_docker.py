from pathlib import Path
from types import SimpleNamespace

import pytest

from src.plugins.pallas_protocol.config import Config
from src.plugins.pallas_protocol.docker_cli import docker_repository_from_ref
from src.plugins.pallas_protocol.service import (
    PallasProtocolService,
    _docker_stderr_suggests_container_name_conflict,
    _docker_stderr_suggests_host_port_bind_conflict,
)
from src.plugins.pallas_protocol.snowluma_docker import (
    build_snowluma_docker_run_argv,
    snowluma_docker_program_dir_marker,
    snowluma_docker_volume_paths,
)


def test_build_snowluma_docker_run_argv_defaults_match_upstream_doc(tmp_path: Path) -> None:
    ad = tmp_path / "inst" / "sldef" / "snowluma"
    ad.mkdir(parents=True)
    cfg = SimpleNamespace(
        pallas_protocol_snowluma_docker_image="motricseven7/snowluma:latest",
        pallas_protocol_snowluma_docker_internal_webui_port=5099,
        pallas_protocol_snowluma_docker_internal_onebot_http_port=3000,
        pallas_protocol_snowluma_docker_internal_onebot_ws_port=3001,
        pallas_protocol_snowluma_docker_shm_size="1g",
        pallas_protocol_snowluma_docker_vnc_passwd="",
        pallas_protocol_snowluma_docker_host_novnc_port=0,
        pallas_protocol_snowluma_docker_host_vnc_port=0,
        pallas_protocol_snowluma_docker_internal_novnc_port=6081,
        pallas_protocol_snowluma_docker_internal_vnc_port=5900,
    )
    account = {
        "id": "accdef",
        "account_data_dir": str(ad),
        "webui_port": 6155,
        "snowluma_docker_host_onebot_http": 3000,
        "snowluma_docker_host_onebot_ws": 3001,
        "snowluma_docker_host_novnc_port": 6081,
        "snowluma_docker_host_vnc_port": 5900,
    }
    argv = build_snowluma_docker_run_argv(account, cfg, lambda a: "1")
    joined = " ".join(argv)
    assert "6155:5099" in joined
    assert "3000:3000" in joined
    assert "3001:3001" in joined
    assert "6081:6081" in joined
    assert "5900:5900" in joined


def test_build_snowluma_docker_run_argv_basic(tmp_path: Path) -> None:
    ad = tmp_path / "inst" / "a1" / "snowluma"
    ad.mkdir(parents=True)
    cfg = SimpleNamespace(
        pallas_protocol_snowluma_docker_image="motricseven7/snowluma:latest",
        pallas_protocol_snowluma_docker_internal_webui_port=5099,
        pallas_protocol_snowluma_docker_internal_onebot_http_port=3000,
        pallas_protocol_snowluma_docker_internal_onebot_ws_port=3001,
        pallas_protocol_snowluma_docker_shm_size="1g",
        pallas_protocol_snowluma_docker_vnc_passwd="",
        pallas_protocol_snowluma_docker_host_novnc_port=0,
        pallas_protocol_snowluma_docker_host_vnc_port=0,
        pallas_protocol_snowluma_docker_internal_novnc_port=6081,
        pallas_protocol_snowluma_docker_internal_vnc_port=5900,
    )
    account = {
        "id": "acc1",
        "account_data_dir": str(ad),
        "webui_port": 6101,
        "snowluma_docker_host_onebot_http": 7101,
        "snowluma_docker_host_onebot_ws": 7102,
    }
    argv = build_snowluma_docker_run_argv(account, cfg, lambda a: "12345")
    assert argv[0] == "run"
    assert "-p" in argv
    assert "6101:5099" in argv
    assert "7101:3000" in argv
    assert "7102:3001" in argv
    assert "SYS_PTRACE" in argv
    assert "seccomp=unconfined" in argv
    assert argv[-1] == "motricseven7/snowluma:latest"
    d1, d2, d3 = snowluma_docker_volume_paths(account)
    assert all(x.is_relative_to(ad) for x in (d1, d2, d3))


def test_snowluma_docker_program_dir_marker() -> None:
    cfg = SimpleNamespace(pallas_protocol_snowluma_docker_image="x/y:tag")
    assert snowluma_docker_program_dir_marker(cfg) == "docker:snowluma:x/y:tag"


def test_snowluma_docker_per_account_novnc_vnc_override(tmp_path: Path) -> None:
    ad = tmp_path / "inst" / "b2" / "snowluma"
    ad.mkdir(parents=True)
    cfg = SimpleNamespace(
        pallas_protocol_snowluma_docker_image="motricseven7/snowluma:latest",
        pallas_protocol_snowluma_docker_internal_webui_port=5099,
        pallas_protocol_snowluma_docker_internal_onebot_http_port=3000,
        pallas_protocol_snowluma_docker_internal_onebot_ws_port=3001,
        pallas_protocol_snowluma_docker_shm_size="1g",
        pallas_protocol_snowluma_docker_vnc_passwd="",
        pallas_protocol_snowluma_docker_host_novnc_port=0,
        pallas_protocol_snowluma_docker_host_vnc_port=0,
        pallas_protocol_snowluma_docker_internal_novnc_port=6081,
        pallas_protocol_snowluma_docker_internal_vnc_port=5900,
    )
    account = {
        "id": "acc2",
        "account_data_dir": str(ad),
        "webui_port": 6102,
        "snowluma_docker_host_onebot_http": 7201,
        "snowluma_docker_host_onebot_ws": 7202,
        "snowluma_docker_host_novnc_port": 16081,
        "snowluma_docker_host_vnc_port": 15900,
    }
    argv = build_snowluma_docker_run_argv(account, cfg, lambda a: "12345")
    joined = " ".join(argv)
    assert "16081:6081" in joined
    assert "15900:5900" in joined


def test_docker_stderr_container_name_conflict_detection() -> None:
    assert _docker_stderr_suggests_container_name_conflict(
        'docker: Error response from daemon: Conflict. The container name "/pallas-proto-sl-1" '
        'is already in use by container "9c0e"'
    )
    assert not _docker_stderr_suggests_container_name_conflict("random failure")


def test_docker_stderr_port_bind_conflict_detection() -> None:
    f = _docker_stderr_suggests_host_port_bind_conflict
    assert f(
        "docker: Error response from daemon: ports are not available: "
        "exposing port TCP 0.0.0.0:6100 -> 127.0.0.1:0: listen tcp 0.0.0.0:6100: bind: "
        "Only one usage of each socket address (protocol/network address/port) is normally permitted."
    )
    assert f("failed to bind port 0.0.0.0:8080/tcp: port is already allocated")
    assert not f("docker: invalid reference format")
    assert not f("")


def test_docker_repository_from_ref() -> None:
    assert docker_repository_from_ref("mlikiowa/napcat-docker:latest") == "mlikiowa/napcat-docker"
    assert docker_repository_from_ref("localhost:5000/nc/app:v1") == "localhost:5000/nc/app"
    assert docker_repository_from_ref("motricseven7/snowluma") == "motricseven7/snowluma"
    assert docker_repository_from_ref("x/y@sha256:abc") == "x/y"


def test_refresh_linux_docker_run_argv_rewrites_cached_args(tmp_path: Path) -> None:
    cfg = Config()
    svc = PallasProtocolService(tmp_path / "pdata", cfg)
    ad = tmp_path / "inst" / "a1" / "snowluma"
    ad.mkdir(parents=True)
    account = {
        "snowluma_linux_docker": True,
        "id": "acc1",
        "account_data_dir": str(ad),
        "webui_port": 7777,
        "snowluma_docker_host_onebot_http": 7101,
        "snowluma_docker_host_onebot_ws": 7102,
        "args": ["run", "-p", "6101:5099"],
    }
    svc._refresh_linux_docker_run_argv(account)
    joined = " ".join(str(x) for x in account["args"])
    assert "7777:5099" in joined
    assert "6101:5099" not in joined


def test_snowluma_allocate_auto_host_ports_avoids_other_accounts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    d = tmp_path / "pdalloc"
    d.mkdir()
    (d / "accounts.json").write_text("{}", encoding="utf-8")
    cfg = Config()
    svc = PallasProtocolService(d, cfg)
    monkeypatch.setattr(
        PallasProtocolService,
        "_is_host_port_available",
        lambda self, port: True,
    )
    p1 = svc._snowluma_docker_allocate_auto_host_ports({"id": "u1", "webui_port": 6100})
    assert p1["onebot_ws"] == p1["onebot_http"] + 1
    assert p1["host_novnc"] != p1["host_vnc"]
    svc._accounts["u1"] = {
        "id": "u1",
        "webui_port": 6100,
        "snowluma_linux_docker": True,
        "snowluma_docker_host_onebot_http": p1["onebot_http"],
        "snowluma_docker_host_onebot_ws": p1["onebot_ws"],
        "snowluma_docker_host_novnc_port": p1["host_novnc"],
        "snowluma_docker_host_vnc_port": p1["host_vnc"],
    }
    p2 = svc._snowluma_docker_allocate_auto_host_ports({"id": "u2", "webui_port": 6105})
    taken = {
        p1["onebot_http"],
        p1["onebot_ws"],
        p1["host_novnc"],
        p1["host_vnc"],
        6100,
        6105,
    }
    assert taken.isdisjoint(
        {p2["onebot_http"], p2["onebot_ws"], p2["host_novnc"], p2["host_vnc"]}
    )
