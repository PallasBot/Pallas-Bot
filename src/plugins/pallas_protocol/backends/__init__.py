"""协议端运行时注册表：按 `protocol_backend` 分派至具体实现。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..contract import DEFAULT_PROTOCOL_BACKEND
from .napcat import NapcatRuntimeBackend
from .protocol import ProtocolRuntimeBackend

ProtocolRuntimeBackendFactory = Callable[[Any], ProtocolRuntimeBackend]

_PROTOCOL_RUNTIME_FACTORIES: dict[str, ProtocolRuntimeBackendFactory] = {}


def register_protocol_runtime_backend(kind: str, factory: ProtocolRuntimeBackendFactory) -> None:
    key = (kind or "").strip().lower()
    if not key:
        msg = "协议端 backend 注册名不能为空"
        raise ValueError(msg)
    _PROTOCOL_RUNTIME_FACTORIES[key] = factory


def registered_protocol_runtime_backends() -> tuple[str, ...]:
    return tuple(sorted(_PROTOCOL_RUNTIME_FACTORIES.keys()))


def make_protocol_runtime_backend(service: Any, kind: str) -> ProtocolRuntimeBackend:
    raw = (kind or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
    factory = _PROTOCOL_RUNTIME_FACTORIES.get(raw)
    if factory is None:
        known = ", ".join(registered_protocol_runtime_backends()) or "(empty)"
        msg = f"未注册的协议端实现: {raw!r}；已注册: {known}"
        raise ValueError(msg)
    return factory(service)


register_protocol_runtime_backend("napcat", lambda s: NapcatRuntimeBackend(s))

__all__ = [
    "NapcatRuntimeBackend",
    "ProtocolRuntimeBackend",
    "make_protocol_runtime_backend",
    "register_protocol_runtime_backend",
    "registered_protocol_runtime_backends",
]
