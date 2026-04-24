"""NapCat Shell 运行时下载、解压与 manifest（与平台启动逻辑解耦）。"""

from .installer import (
    JobStatus,
    NapCatRuntimeStore,
    RuntimeManifest,
    asset_is_windows_onekey,
    default_release_asset_for_platform,
    find_napcat_program_dir,
    find_onekey_post_install_program_dir,
    resolve_program_dir_under_extract,
)

__all__ = [
    "JobStatus",
    "NapCatRuntimeStore",
    "RuntimeManifest",
    "asset_is_windows_onekey",
    "default_release_asset_for_platform",
    "find_napcat_program_dir",
    "find_onekey_post_install_program_dir",
    "resolve_program_dir_under_extract",
]
