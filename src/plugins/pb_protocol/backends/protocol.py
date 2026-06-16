"""协议端运行时抽象：新栈实现 ``ProtocolRuntimeBackend``，并用 ``register_protocol_runtime_backend`` 登记。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class ProtocolRuntimeBackend(Protocol):
    """单账号协议栈的配置准备与校验"""

    kind: str

    def apply_defaults(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        """补齐 command/args/program_dir/account_data_dir 等默认值。"""
        ...

    def prepare_dirs(self, account: dict) -> None:
        """创建账号数据目录等。"""
        ...

    def sync_all_configs(self, account: dict, resolve_qq: Callable[[dict], str]) -> None:
        """写入协议栈所需的全部配置文件。"""
        ...

    def sync_onebot(self, account: dict, resolve_qq: Callable[[dict], str]) -> None: ...

    def sync_webui(self, account: dict, resolve_qq: Callable[[dict], str]) -> None: ...

    def read_webui_into_account(self, account: dict) -> bool: ...

    def get_account_configs(self, account: dict, resolve_qq: Callable[[dict], str]) -> dict[str, Any]: ...

    def update_account_configs(
        self, account: dict, payload: dict, resolve_qq: Callable[[dict], str]
    ) -> dict[str, Any]: ...

    def check_launch_issues(self, account: dict, resolve_qq: Callable[[dict], str]) -> list[str]: ...

    def describe_account_data_paths(self, account: dict) -> dict[str, object]: ...


__all__ = ["ProtocolRuntimeBackend"]
