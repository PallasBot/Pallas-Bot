"""入站热路径快照的健康状态。"""

from __future__ import annotations

from typing import Any


def ingress_snapshot_health() -> dict[str, dict[str, Any]]:
    from pallas.product.ban_gate.snapshot import ban_gate_snapshot_status

    health: dict[str, dict[str, Any]] = {"ban_gate": ban_gate_snapshot_status()}
    try:
        from packages.help.plugin_manager import disabled_plugin_snapshot_status

        health["disabled_plugins"] = disabled_plugin_snapshot_status()
    except Exception:
        health["disabled_plugins"] = {"ready": False, "available": False}
    return health
