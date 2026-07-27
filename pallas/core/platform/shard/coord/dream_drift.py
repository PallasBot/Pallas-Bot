"""分片 worker：跨片同步做梦群注册与梦话漂流投递。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.dream.drift")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
