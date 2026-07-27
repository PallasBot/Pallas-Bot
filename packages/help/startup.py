from pallas.api.storage import register_plugin_storage_startup_hook
from pallas.product.llm.tools.startup import register_llm_tools_startup_hook

from . import event_preprocessor  # noqa: F401
from .style_cache import refresh_style_cache

refresh_style_cache()
register_plugin_storage_startup_hook()
# hub 不加载 llm_chat，但仍需在插件全部就绪后刷新 help 等 command tools
register_llm_tools_startup_hook()
