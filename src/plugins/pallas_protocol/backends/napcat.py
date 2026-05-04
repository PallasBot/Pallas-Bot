"""NapCat 协议栈：委托现有 LaunchManager / AccountConfigManager。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..service import PallasProtocolService


class NapcatRuntimeBackend:
    """当前默认协议端实现，行为与抽出抽象前一致。"""

    kind = "napcat"

    def __init__(self, service: PallasProtocolService) -> None:
        self._service = service

    def apply_defaults(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        self._service._launch.apply_defaults(account, resolve_qq)

    def prepare_dirs(self, account: dict) -> None:
        self._service._launch.prepare_dirs(account)

    def sync_all_configs(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        self._service._configs.sync_onebot(account, resolve_qq)
        self._service._configs.sync_napcat_core(account, resolve_qq)
        self._service._configs.sync_webui(account, resolve_qq)

    def sync_onebot(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        self._service._configs.sync_onebot(account, resolve_qq)

    def sync_webui(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        self._service._configs.sync_webui(account, resolve_qq)

    def read_webui_into_account(self, account: dict) -> bool:
        return self._service._configs.read_webui_into_account(account)

    def get_account_configs(self, account: dict, resolve_qq: Callable[[dict], str]) -> dict[str, Any]:
        return self._service._configs.get_account_configs(account, resolve_qq)

    def update_account_configs(self, account: dict, payload: dict, resolve_qq: Callable[[dict], str]) -> dict[str, Any]:
        return self._service._configs.update_account_configs(account, payload, resolve_qq)

    def check_launch_issues(self, account: dict, resolve_qq: Callable[[dict], str]) -> list[str]:
        return self._service._launch.check_launch_issues(account, resolve_qq)

    def describe_account_data_paths(self, account: dict) -> dict[str, object]:
        return self._service._launch.describe_account_data_paths(account)


__all__ = ["NapcatRuntimeBackend"]
