"""SnowLuma 协议栈：扁平 OneBot、runtime.json；启动由 LaunchManager 的 snowluma 分支处理。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..service import PallasProtocolService


class SnowlumaRuntimeBackend:
    kind = "snowluma"

    def __init__(self, service: PallasProtocolService) -> None:
        self._service = service

    def apply_defaults(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        self._service._launch.apply_defaults(account, resolve_qq)

    def prepare_dirs(self, account: dict) -> None:
        self._service._launch.prepare_dirs(account)

    def sync_all_configs(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        from ..snowluma_config import sync_snowluma_onebot, sync_snowluma_runtime_json

        cfg = self._service._configs
        wmin = int(getattr(self._service._config, "pallas_protocol_webui_port_min", 6099) or 6099)
        pc = self._service._config
        sync_snowluma_runtime_json(account, webui_port_fallback_min=wmin, plugin_config=pc)
        sync_snowluma_onebot(cfg, account, resolve_qq, plugin_config=pc)

    def sync_onebot(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        from ..snowluma_config import sync_snowluma_onebot

        sync_snowluma_onebot(
            self._service._configs,
            account,
            resolve_qq,
            plugin_config=self._service._config,
        )

    def sync_webui(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        from ..snowluma_config import sync_snowluma_runtime_json

        wmin = int(getattr(self._service._config, "pallas_protocol_webui_port_min", 6099) or 6099)
        sync_snowluma_runtime_json(account, webui_port_fallback_min=wmin, plugin_config=self._service._config)

    def read_webui_into_account(self, account: dict) -> bool:
        from ..snowluma_config import read_snowluma_runtime_into_account

        return read_snowluma_runtime_into_account(account)

    def get_account_configs(self, account: dict, resolve_qq: Callable[[dict], str]) -> dict[str, Any]:
        from ..snowluma_config import get_snowluma_account_configs

        return get_snowluma_account_configs(self._service._configs, account, resolve_qq)

    def update_account_configs(self, account: dict, payload: dict, resolve_qq: Callable[[dict], str]) -> dict[str, Any]:
        from ..snowluma_config import update_snowluma_account_configs

        return update_snowluma_account_configs(self._service._configs, account, payload, resolve_qq)

    def check_launch_issues(self, account: dict, resolve_qq: Callable[[dict], str]) -> list[str]:
        return self._service._launch.check_launch_issues(account, resolve_qq)

    def describe_account_data_paths(self, account: dict) -> dict[str, object]:
        return self._service._launch.describe_account_data_paths(account)


__all__ = ["SnowlumaRuntimeBackend"]
