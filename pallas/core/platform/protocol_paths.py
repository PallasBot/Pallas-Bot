"""协议端（NapCat / SnowLuma 等）共享数据路径锚点。

协议端插件 ``pallas_plugin_protocol`` 将账号数据写入 ``data/pallas_protocol/``，
其中 ``accounts.json`` 是全集群舰队/分片注册的账号清单来源。内核多处（分片 data_sync、
fleet 集合、worker 扩容、控制台只读快照）都需要解析该目录与文件，统一收敛到此处，
避免散落的字符串常量与硬编码路径漂移。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

#: 协议端插件的 data 子目录名（与 ``pallas_plugin_protocol`` 的 ``plugin_data_dir`` 一致）。
PROTOCOL_PLUGIN = "pallas_protocol"
#: 协议端账号清单文件名。
PROTOCOL_ACCOUNTS_FILE = "accounts.json"


def protocol_data_dir(*, create: bool = False) -> Path:
    """协议端账号数据目录 ``data/pallas_protocol/``。"""
    return plugin_data_dir(PROTOCOL_PLUGIN, create=create)


def protocol_accounts_path(*, create: bool = False) -> Path:
    """协议端账号清单 ``data/pallas_protocol/accounts.json``（可能尚不存在）。"""
    return protocol_data_dir(create=create) / PROTOCOL_ACCOUNTS_FILE
