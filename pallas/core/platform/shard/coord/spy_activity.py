"""卧底同群 activity 协调。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.spy.activity")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
