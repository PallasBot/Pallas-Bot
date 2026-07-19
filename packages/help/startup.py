from pallas.core.storage.startup import register_plugin_storage_startup_hook

from . import event_preprocessor  # noqa: F401
from .style_cache import refresh_style_cache

refresh_style_cache()
register_plugin_storage_startup_hook()
