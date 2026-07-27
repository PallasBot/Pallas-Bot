"""分片 hub：将 MAA getTask / reportStatus 转发到登记 worker。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.maa.http_forward")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
