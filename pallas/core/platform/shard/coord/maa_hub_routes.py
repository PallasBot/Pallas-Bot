"""分片 hub：挂载 MAA HTTP 转发路由。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.maa.hub_routes")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
