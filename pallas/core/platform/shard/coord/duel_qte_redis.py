"""决斗 QTE Redis 存储与 greeting 让路。"""

import importlib as _importlib

_impl = _importlib.import_module("pallas.extensions.coord.duel.qte_redis")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
