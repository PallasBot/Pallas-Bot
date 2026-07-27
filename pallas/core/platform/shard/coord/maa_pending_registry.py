"""分片：MAA 待拉取任务队列。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.maa.pending_registry")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
