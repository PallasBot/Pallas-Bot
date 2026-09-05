"""插件目录（拆分包）。

对外保持模块路径 ``pallas.console.webui.plugin_catalog`` 的导入面完整，
测试可继续经该命名空间打桩共享符号。
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from pallas.console.webui.community_plugin_assets import resolve_community_plugin_icon
from pallas.console.webui.community_plugin_index import (
    DEFAULT_INDEX_REL,
    LOCAL_INDEX_REL,
    load_index_from_path,
)
from pallas.console.webui.community_plugin_registry import resolve_community_plugin_avatar
from pallas.console.webui.local_plugin_uninstall import plugin_uninstall_info
from pallas.console.webui.plugin_package_assets import resolve_plugin_package_visual_urls
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_MODULES,
    extra_package_for_plugin,
    is_bundled_play_plugin,
    is_core_plugin,
    is_extra_plugin,
)
from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id

_PLUGINS_ROOT = PROJECT_ROOT / "packages"

from pallas.console.webui.plugin_catalog.catalog import (  # noqa: E402
    _loaded_plugin_index,
    build_plugin_catalog_rows,
    catalog_plugin_source,
    community_plugin_row_for_plugin,
)
from pallas.console.webui.plugin_catalog.classify import (  # noqa: E402
    PluginSourceKind,
    classify_distribution_source,
    normalize_distribution_name,
)
from pallas.console.webui.plugin_catalog.config_module import (  # noqa: E402
    _config_py_path_for_package_module,
    _load_config_class_isolated,
    _package_dir_to_module_id,
    load_config_class_for_package,
    module_has_config_module,
    package_has_config_module,
    resolve_catalog_plugin_module,
)
from pallas.console.webui.plugin_catalog.discovery import (  # noqa: E402
    _package_dir_posix,
    discover_extra_plugin_packages,
    discover_plugin_packages,
    discover_pyproject_plugin_modules,
    infer_plugin_source,
    is_infrastructure_plugin_name,
    module_dir_rel,
    plugin_source_from_module_path,
)
from pallas.console.webui.plugin_catalog.identity import (  # noqa: E402
    _module_short_name,
    resolved_plugin_identity,
)
from pallas.console.webui.plugin_catalog.metadata import (  # noqa: E402
    _parse_plugin_metadata_stub,
    _pip_plugin_metadata_stub,
    metadata_to_dict,
)
from pallas.console.webui.plugin_catalog.role import (  # noqa: E402
    expected_loaded_in_catalog_process,
    package_load_role,
    resolve_catalog_process_role,
    should_show_in_plugin_catalog,
)
from pallas.console.webui.plugin_catalog.version import (  # noqa: E402
    installed_distribution_version,
    plugin_version,
)
from pallas.console.webui.plugin_catalog.visuals import (  # noqa: E402
    _first_visual_url,
    _icon_only_from_layer,
    _merge_catalog_visual_layers,
    _resolve_remote_catalog_visuals,
    resolve_catalog_visuals,
)

__all__ = [
    "DEFAULT_INDEX_REL",
    "EXTRA_PACKAGE_MODULES",
    "LOCAL_INDEX_REL",
    "PROJECT_ROOT",
    "PluginSourceKind",
    "_PLUGINS_ROOT",
    "_config_py_path_for_package_module",
    "_first_visual_url",
    "_icon_only_from_layer",
    "_load_config_class_isolated",
    "_loaded_plugin_index",
    "_merge_catalog_visual_layers",
    "_module_short_name",
    "_package_dir_posix",
    "_package_dir_to_module_id",
    "_parse_plugin_metadata_stub",
    "_pip_plugin_metadata_stub",
    "_resolve_remote_catalog_visuals",
    "build_plugin_catalog_rows",
    "canonical_plugin_id",
    "catalog_plugin_source",
    "classify_distribution_source",
    "community_plugin_row_for_plugin",
    "discover_extra_plugin_packages",
    "discover_plugin_packages",
    "discover_pyproject_plugin_modules",
    "expected_loaded_in_catalog_process",
    "extra_package_for_plugin",
    "infer_plugin_source",
    "installed_distribution_version",
    "is_bundled_play_plugin",
    "is_core_plugin",
    "is_extra_plugin",
    "is_infrastructure_plugin_name",
    "load_config_class_for_package",
    "load_index_from_path",
    "metadata_to_dict",
    "module_dir_rel",
    "module_has_config_module",
    "normalize_distribution_name",
    "package_has_config_module",
    "package_load_role",
    "plugin_source_from_module_path",
    "plugin_uninstall_info",
    "plugin_version",
    "resolve_catalog_plugin_module",
    "resolve_catalog_process_role",
    "resolve_catalog_visuals",
    "resolve_community_plugin_avatar",
    "resolve_community_plugin_icon",
    "resolve_plugin_package_visual_urls",
    "resolved_plugin_identity",
    "should_show_in_plugin_catalog",
]
