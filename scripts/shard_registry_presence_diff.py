#!/usr/bin/env python3
"""对比 registry 登记分片与 worker_presence 实际 WS 在线（运维排查用）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ  # noqa: E402

apply_repo_settings_to_environ()

from pallas.core.platform.shard.presence import read_presence_bots  # noqa: E402
from pallas.core.platform.shard.registry.store import get_shard_registry  # noqa: E402


def main() -> int:
    reg = get_shard_registry()
    presence = read_presence_bots()
    online = {int(k) for k in presence}
    rows: list[dict] = []
    for shard in reg.shards:
        if shard.role == "test":
            continue
        for bot_id in shard.bot_ids:
            qq = int(bot_id)
            rows.append({
                "shard_id": shard.id,
                "port": shard.port,
                "qq": qq,
                "registered": True,
                "ws_online": qq in online,
                "nickname": (presence.get(str(qq)) or {}).get("nickname") or "",
            })
    missing = [r for r in rows if not r["ws_online"]]
    extra = [
        {"qq": int(k), "shard_id": v.get("shard_id"), "nickname": v.get("nickname")}
        for k, v in presence.items()
        if int(k) not in {int(x) for s in reg.shards for x in s.bot_ids}
    ]
    out = {
        "registered_total": len(rows),
        "online_total": sum(1 for r in rows if r["ws_online"]),
        "missing_ws": missing,
        "presence_not_in_registry": extra,
        "by_shard": rows,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if missing:
        print(f"未连接 WS: {len(missing)} 只（见 JSON missing_ws）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
