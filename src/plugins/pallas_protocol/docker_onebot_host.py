"""Linux Docker 下 NapCat/SnowLuma 容器访问宿主机 Bot 的 WS 主机解析。"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any


def linux_default_route_gateway() -> str | None:
    """读取 Linux 默认路由网关，非 Linux 或失败时返回 None。"""
    try:
        with Path("/proc/net/route").open(encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.split()
                if len(parts) < 8:
                    continue
                _iface, dest_hex, gateway_hex, _, _, _, _, mask_hex = parts[:8]
                if dest_hex != "00000000" or mask_hex != "00000000":
                    continue
                if not gateway_hex or gateway_hex == "00000000":
                    continue
                try:
                    gw_be = bytes.fromhex(gateway_hex)
                except ValueError:
                    continue
                if len(gw_be) != 4:
                    continue
                return socket.inet_ntoa(gw_be[::-1])
    except OSError:
        return None
    return None


def effective_docker_onebot_host(raw: str | None, *, docker_network_mode: str) -> str:
    """返回写入 onebot 配置的主机名或 IP。

    - 非空且非 ``auto``：原样使用（便于 Compose 同网主机名等）。
    - ``host`` 网络：自动为 ``127.0.0.1``（与宿主机网络栈一致）。
    - ``bridge`` 等且自动：**Linux** 优先默认路由网关（读 ``/proc/net/route``），失败则
      ``172.17.0.1``；容器内不依赖 ``host.docker.internal`` 解析。**非 Linux**（如仅在本机
      配协议端）仍可用 ``host.docker.internal``（通常配合 Docker Desktop）。
    - ``docker run`` 仍会加 ``--add-host=host.docker.internal:host-gateway``，便于镜像内其它逻辑解析。
    """
    s = (raw or "").strip()
    if s and s.lower() != "auto":
        return s
    mode = (docker_network_mode or "bridge").strip().lower()
    if mode == "host":
        return "127.0.0.1"
    if sys.platform.startswith("linux"):
        return linux_default_route_gateway() or "172.17.0.1"
    return "host.docker.internal"


def resolve_docker_onebot_host_from_config(config: Any) -> str:
    raw = getattr(config, "pallas_protocol_docker_onebot_host", None)
    nm = getattr(config, "pallas_protocol_docker_network_mode", None)
    return effective_docker_onebot_host(
        str(raw or "").strip(),
        docker_network_mode=str(nm or "bridge").strip() or "bridge",
    )


def docker_host_gateway_extra_args() -> list[str]:
    """bridge 时可选注入，便于容器内解析 ``host.docker.internal``（Docker 20.10+）。"""
    return ["--add-host", "host.docker.internal:host-gateway"]
