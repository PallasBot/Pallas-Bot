"""跨 worker 同群决斗互斥。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.duel.group")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
