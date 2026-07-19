"""service_gateways 内核运行时注册。"""

from __future__ import annotations

import nonebot

_CONNECTIVITY_LOADED = False


def register_service_gateways_runtime() -> None:
    global _CONNECTIVITY_LOADED
    if _CONNECTIVITY_LOADED:
        return
    nonebot.load_plugin("pallas.product.service_gateways.connectivity")
    _CONNECTIVITY_LOADED = True
