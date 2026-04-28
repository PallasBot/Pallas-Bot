"""协议端插件的公共约定：账号实现类型、HTTP 路径与扩展点（与具体进程启动细节解耦）。"""

from __future__ import annotations

# 默认协议实现
DEFAULT_PROTOCOL_BACKEND: str = "napcat"
# 账号协议字段名
ACCOUNT_PROTOCOL_BACKEND_KEY: str = "protocol_backend"

# 协议页面前缀
PROTOCOL_HTTP_PREFIX: str = "/protocol"


def protocol_web_mount_path(*, implementation_slug: str) -> str:
    """返回 ``/protocol/<slug>``；slug 空时回退到 DEFAULT_PROTOCOL_BACKEND。"""
    s = (implementation_slug or "").strip().strip("/")
    if not s:
        s = DEFAULT_PROTOCOL_BACKEND
    return f"{PROTOCOL_HTTP_PREFIX}/{s}"


def resolve_public_mount_path(*, path_override: str, implementation_slug: str) -> str:
    """解析管理页挂载基路径。

    - ``path_override`` 非空：视为整段 URL（可指向任意路径，用于完全自定义）。
    - 否则：``protocol_web_mount_path(implementation_slug=...)``；slug 空则用 DEFAULT_PROTOCOL_BACKEND。
    """
    po = (path_override or "").strip()
    if po:
        return po.rstrip("/")
    return protocol_web_mount_path(implementation_slug=implementation_slug)
