"""分片：MAA 远控 user → worker 登记，供 hub 转发 getTask / reportStatus。"""

import importlib as _importlib

from pallas.core.platform.shard import worker_port as _worker_port

_impl = _importlib.import_module("pallas.extensions.coord.maa.route_registry")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
globals()["current_worker_port"] = _worker_port.current_worker_port
