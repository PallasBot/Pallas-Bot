"""协议端运行时注册表：按账号 `protocol_backend` 字段分派。"""

# 新协议栈：实现 ProtocolRuntimeBackend 后在此 register；kind 与账号里存的字符串同形且小写匹配。

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..contract import DEFAULT_PROTOCOL_BACKEND
from .napcat import NapcatRuntimeBackend
from .protocol import ProtocolRuntimeBackend
from .snowluma import SnowlumaRuntimeBackend

ProtocolRuntimeBackendFactory = Callable[[Any], ProtocolRuntimeBackend]

_PROTOCOL_RUNTIME_FACTORIES: dict[str, ProtocolRuntimeBackendFactory] = {}


def register_protocol_runtime_backend(kind: str, factory: ProtocolRuntimeBackendFactory) -> None:
    """登记一种实现；factory 接收 PallasProtocolService，返回该后端的 RuntimeBackend 实例。应在插件加载阶段调用。"""
    key = (kind or "").strip().lower()
    if not key:
        msg = "协议端 backend 注册名不能为空"
        raise ValueError(msg)
    _PROTOCOL_RUNTIME_FACTORIES[key] = factory


def registered_protocol_runtime_backends() -> tuple[str, ...]:
    return tuple(sorted(_PROTOCOL_RUNTIME_FACTORIES.keys()))


def make_protocol_runtime_backend(service: Any, kind: str) -> ProtocolRuntimeBackend:
    """按 kind 取工厂；空串回退到 contract.DEFAULT_PROTOCOL_BACKEND。未登记则 ValueError。"""
    raw = (kind or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
    factory = _PROTOCOL_RUNTIME_FACTORIES.get(raw)
    if factory is None:
        known = ", ".join(registered_protocol_runtime_backends()) or "(empty)"
        msg = f"未注册的协议端实现: {raw!r}；已注册: {known}"
        raise ValueError(msg)
    return factory(service)


# 内置：与 DEFAULT_PROTOCOL_BACKEND 一致
register_protocol_runtime_backend("napcat", lambda s: NapcatRuntimeBackend(s))
register_protocol_runtime_backend("snowluma", lambda s: SnowlumaRuntimeBackend(s))

__all__ = [
    "NapcatRuntimeBackend",
    "SnowlumaRuntimeBackend",
    "ProtocolRuntimeBackend",
    "make_protocol_runtime_backend",
    "register_protocol_runtime_backend",
    "registered_protocol_runtime_backends",
]
