"""协议端插件的公共约定：账号实现类型、HTTP 路径与扩展点。"""

from __future__ import annotations

import re
from pathlib import Path

# 默认协议实现
DEFAULT_PROTOCOL_BACKEND: str = "napcat"
SNOWLUMA_PROTOCOL_BACKEND: str = "snowluma"
# 未配置 pallas_protocol_web_implementation 时，管理页 URL 第二段
DEFAULT_PROTOCOL_WEB_MOUNT_SLUG: str = "console"
# 账号协议字段名；取值对应运行时注册表中的 kind
ACCOUNT_PROTOCOL_BACKEND_KEY: str = "protocol_backend"
# 账号选用托管解压子目录对应的 Release 标记
MANAGED_RUNTIME_TAG_KEY: str = "managed_runtime_tag"

# 协议页面前缀
PROTOCOL_HTTP_PREFIX: str = "/protocol"


def protocol_web_mount_path(*, implementation_slug: str) -> str:
    """返回 ``/protocol/<slug>``；slug 空时回退到 DEFAULT_PROTOCOL_WEB_MOUNT_SLUG。"""
    s = (implementation_slug or "").strip().strip("/")
    if not s:
        s = DEFAULT_PROTOCOL_WEB_MOUNT_SLUG
    return f"{PROTOCOL_HTTP_PREFIX}/{s}"


def resolve_public_mount_path(*, path_override: str, implementation_slug: str) -> str:
    """解析管理页挂载基路径。

    - ``path_override`` 非空：视为整段 URL。
    - 否则：``protocol_web_mount_path(implementation_slug=...)``；slug 空则用 DEFAULT_PROTOCOL_WEB_MOUNT_SLUG。
    """
    po = (path_override or "").strip()
    if po:
        return po.rstrip("/")
    return protocol_web_mount_path(implementation_slug=implementation_slug)


def normalize_instance_folder_segment(kind: str) -> str:
    """``instances/<账号id>/<本段>/`` 中的目录名，与 ``protocol_backend`` 对齐，仅含路径安全字符。"""
    s = (kind or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = s.strip("-_.")
    if not s:
        s = DEFAULT_PROTOCOL_BACKEND
    return s[:64]


def resolve_default_account_data_dir(instances_root: Path, account_id: str, backend_kind: str) -> Path:
    """无显式 ``account_data_dir`` 时的默认数据目录：``instances/<id>/<backend>/``。

    若磁盘上仍存在历史布局 ``instances/<id>/``，且新布局目录尚不存在，
    则继续沿用旧路径，避免破坏已有 NapCat 数据；否则使用新布局路径（可能尚不存在，由
    ``prepare_dirs`` 创建）。"""
    clean_id = (account_id or "").strip()
    if not clean_id:
        return Path(instances_root).resolve()

    seg = normalize_instance_folder_segment(backend_kind)
    nested = (instances_root / clean_id / seg).resolve()
    legacy = (instances_root / clean_id).resolve()
    if nested.exists() and nested.is_dir():
        return nested
    if legacy.exists() and legacy.is_dir() and (legacy / "config").is_dir() and not nested.exists():
        return legacy
    return nested
