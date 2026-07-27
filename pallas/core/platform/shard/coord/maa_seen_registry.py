"""分片：MAA getTask 轮询活跃时间。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.maa.seen_registry")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
