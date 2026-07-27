"""跨 worker「八角笼」：各分片登记本群在线牛，汇总后统一随机配对。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.duel.cage")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
