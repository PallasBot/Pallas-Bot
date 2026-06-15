"""load_plugin 前读 global_disabled_plugins.json。"""

from __future__ import annotations

import json
from functools import lru_cache

from src.foundation.paths import plugin_data_dir

_BUILTIN_HELP_HIDDEN_PLUGINS = frozenset({
    "pallas_webui",
    "pallas_protocol",
    "ingress_gate",
    "pallas_console_metrics",
    "community_stats",
    "relogin_forward",
    "maa_hub",
})

STARTUP_GLOBAL_DISABLE_PROTECTED = frozenset(sorted(_BUILTIN_HELP_HIDDEN_PLUGINS | frozenset({"help", "ingress_gate"})))

_FILE = "global_disabled_plugins.json"


@lru_cache(maxsize=1)
def startup_global_disabled_plugin_names() -> frozenset[str]:
    path = plugin_data_dir("help") / _FILE
    if not path.exists():
        return frozenset()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return frozenset()
    if not isinstance(raw, dict):
        return frozenset()
    vals = raw.get("disabled_plugins", [])
    if not isinstance(vals, list):
        return frozenset()
    protected = STARTUP_GLOBAL_DISABLE_PROTECTED
    return frozenset(str(x).strip() for x in vals if str(x).strip() and str(x).strip() not in protected)
