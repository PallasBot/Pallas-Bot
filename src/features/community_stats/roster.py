"""社区主站气泡墙 opt-in 名册（同步组装，供心跳 payload 使用）。"""

from __future__ import annotations

from datetime import date, timedelta


def rolling_message_weight_by_self_id(*, days: int = 7) -> dict[str, int]:
    """近 N 自然日每账号消息量（收+发），数据来自控制台按日统计落盘。"""
    if days < 1:
        days = 1
    from src.plugins.pallas_webui import daily_stats_store

    today = date.today()
    start = today - timedelta(days=days - 1)
    rows, _, _ = daily_stats_store.load_range(
        self_id=None,
        start_day=start.isoformat(),
        end_day=today.isoformat(),
    )
    weights: dict[str, int] = {}
    for row in rows:
        sid = str(row.get("self_id") or "").strip()
        if not sid:
            continue
        received = max(0, int(row.get("received", 0)))
        sent = max(0, int(row.get("sent", 0)))
        weights[sid] = weights.get(sid, 0) + received + sent
    return weights


def build_public_roster_entries(
    *,
    max_entries: int = 256,
    show_qq_by_account: dict[int, bool] | None = None,
) -> list[dict[str, object]]:
    from src.console.webui.protocol_accounts import protocol_account_display_names
    from src.plugins.bot_status.list_mode import cluster_online_bot_ids_for_status, status_inventory_bot_ids

    inventory = status_inventory_bot_ids()
    if not inventory:
        return []

    online_ids = cluster_online_bot_ids_for_status()
    names = protocol_account_display_names()
    weights = rolling_message_weight_by_self_id(days=7)
    qq_flags = show_qq_by_account or {}

    entries: list[dict[str, object]] = []
    for qq in sorted(inventory):
        if not bool(qq_flags.get(int(qq), True)):
            continue
        sid = str(qq)
        nickname = (names.get(sid) or "").strip() or f"牛 {qq % 10000}"
        weight = min(10_000_000, max(0, weights.get(sid, 0)))
        entries.append({
            "qq": int(qq),
            "nickname": nickname[:64],
            "online": int(qq) in online_ids,
            "message_weight": weight,
        })
        if len(entries) >= max_entries:
            break
    return entries
