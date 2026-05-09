from __future__ import annotations

import io
from unittest.mock import MagicMock


def test_linux_default_route_gateway_reads_proc_net_route(monkeypatch) -> None:
    from src.plugins.pallas_protocol import docker_onebot_host as m

    content = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
        "docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\n"
        "eth0\t00000000\t010011AC\t0003\t0\t0\t100\t00000000\n"
    )
    real_open = m.Path.open

    def fake_open(self, *args, **kwargs):
        norm = str(self).replace("\\", "/")
        if norm.endswith("/proc/net/route"):
            return io.StringIO(content)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(m.Path, "open", fake_open)
    assert m.linux_default_route_gateway() == "172.17.0.1"


def test_effective_docker_onebot_host_explicit_and_auto(monkeypatch) -> None:
    from src.plugins.pallas_protocol import docker_onebot_host as m

    monkeypatch.setattr(m, "linux_default_route_gateway", lambda: "10.200.0.1")
    monkeypatch.setattr(m.sys, "platform", "linux")
    assert m.effective_docker_onebot_host("", docker_network_mode="bridge") == "10.200.0.1"
    assert m.effective_docker_onebot_host("auto", docker_network_mode="bridge") == "10.200.0.1"

    monkeypatch.setattr(m, "linux_default_route_gateway", lambda: None)
    assert m.effective_docker_onebot_host("", docker_network_mode="bridge") == "172.17.0.1"

    monkeypatch.setattr(m.sys, "platform", "win32")
    assert m.effective_docker_onebot_host("", docker_network_mode="bridge") == "host.docker.internal"

    assert m.effective_docker_onebot_host("", docker_network_mode="host") == "127.0.0.1"
    assert m.effective_docker_onebot_host("10.0.0.2", docker_network_mode="bridge") == "10.0.0.2"


def test_resolve_docker_onebot_host_from_config_reads_network_mode() -> None:
    from src.plugins.pallas_protocol.docker_onebot_host import resolve_docker_onebot_host_from_config

    cfg = MagicMock()
    cfg.pallas_protocol_docker_onebot_host = ""
    cfg.pallas_protocol_docker_network_mode = "host"
    assert resolve_docker_onebot_host_from_config(cfg) == "127.0.0.1"


def test_build_napcat_docker_bridge_adds_host_gateway(tmp_path) -> None:
    from src.plugins.pallas_protocol.linux_docker import build_docker_run_argv

    ad = tmp_path / "acct"
    (ad / "config").mkdir(parents=True)
    (ad / ".config" / "QQ").mkdir(parents=True)
    (ad / "cache").mkdir(parents=True)

    cfg = MagicMock()
    cfg.pallas_protocol_docker_image = "mlikiowa/napcat-docker:latest"
    cfg.pallas_protocol_docker_internal_webui_port = 6099
    cfg.pallas_protocol_docker_network_mode = "bridge"
    cfg.pallas_protocol_docker_uid = 1000
    cfg.pallas_protocol_docker_gid = 1000

    account = {"id": "t1", "account_data_dir": str(ad), "webui_port": 6099}
    argv = build_docker_run_argv(account, cfg, lambda _: "123456")
    joined = " ".join(argv)
    assert "--add-host" in argv
    assert "host.docker.internal:host-gateway" in joined


def test_build_napcat_docker_host_network_skips_host_mapping(tmp_path) -> None:
    from src.plugins.pallas_protocol.linux_docker import build_docker_run_argv

    ad = tmp_path / "acct2"
    (ad / "config").mkdir(parents=True)
    (ad / ".config" / "QQ").mkdir(parents=True)
    (ad / "cache").mkdir(parents=True)

    cfg = MagicMock()
    cfg.pallas_protocol_docker_image = "mlikiowa/napcat-docker:latest"
    cfg.pallas_protocol_docker_internal_webui_port = 6099
    cfg.pallas_protocol_docker_network_mode = "host"
    cfg.pallas_protocol_docker_uid = 1000
    cfg.pallas_protocol_docker_gid = 1000

    account = {"id": "t2", "account_data_dir": str(ad), "webui_port": 6099}
    argv = build_docker_run_argv(account, cfg, lambda _: "123456")
    assert "host.docker.internal" not in " ".join(argv)


def test_build_snowluma_docker_adds_host_gateway(tmp_path) -> None:
    from src.plugins.pallas_protocol.snowluma_docker import build_snowluma_docker_run_argv

    ad = tmp_path / "sl"
    sl_base = ad / "docker" / "snowluma"
    (sl_base / "snowluma-data").mkdir(parents=True)
    (sl_base / "dot-config").mkdir(parents=True)
    (sl_base / "dot-local-share").mkdir(parents=True)

    cfg = MagicMock()
    cfg.pallas_protocol_snowluma_docker_image = "motricseven7/snowluma:latest"
    cfg.pallas_protocol_snowluma_docker_internal_webui_port = 5099
    cfg.pallas_protocol_snowluma_docker_internal_onebot_http_port = 3000
    cfg.pallas_protocol_snowluma_docker_internal_onebot_ws_port = 3001
    cfg.pallas_protocol_snowluma_docker_shm_size = "1g"
    cfg.pallas_protocol_snowluma_docker_vnc_passwd = ""
    cfg.pallas_protocol_snowluma_docker_host_novnc_port = 0
    cfg.pallas_protocol_snowluma_docker_host_vnc_port = 0
    cfg.pallas_protocol_snowluma_docker_internal_novnc_port = 6081
    cfg.pallas_protocol_snowluma_docker_internal_vnc_port = 5900

    account = {
        "id": "s1",
        "account_data_dir": str(ad),
        "webui_port": 5099,
        "snowluma_docker_host_onebot_http": 13000,
        "snowluma_docker_host_onebot_ws": 13001,
    }
    argv = build_snowluma_docker_run_argv(account, cfg, lambda _: "1")
    assert "host.docker.internal:host-gateway" in " ".join(argv)
