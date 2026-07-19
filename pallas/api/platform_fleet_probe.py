"""舰队探测注册 facade：供插件注册「群内本地舰队成员」探测回调。"""

from pallas.core.platform.multi_bot.group_fleet_probe import (
    list_local_fleet_bots_in_group,
    register_fleet_probe,
)

__all__ = [
    "list_local_fleet_bots_in_group",
    "register_fleet_probe",
]
