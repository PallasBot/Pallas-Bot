from pydantic import AliasChoices, BaseModel, Field

from pallas.console.webui import install_hot_reload_config, plugin_config_proxy
from pallas.console.webui.field_help import field_help


class Config(BaseModel, extra="ignore"):
    llm_chat_system_prompt_path: str = Field(
        default="",
        validation_alias=AliasChoices("llm_chat_system_prompt_path", "ollama_system_prompt_path"),
        description=field_help(
            "自定义 system prompt 文件路径",
            "留空使用 compile_persona_prompt 默认；可为相对仓库根的路径",
        ),
    )
    llm_chat_min_priority: int = Field(
        default=50,
        ge=1,
        le=99,
        validation_alias=AliasChoices("llm_chat_min_priority", "ollama_min_priority"),
        description=field_help(
            "LLM 闲聊指令优先级（数值越大越靠后）",
            "群内 @ 闲聊默认 51；卧底述词等优先于 LLM 闲聊",
        ),
    )


def on_llm_chat_config_reload(cfg: Config) -> None:
    from packages.help.plugin_availability import invalidate_plugin_help_availability_cache
    from packages.llm_chat.prompts import clear_system_prompt_cache

    _ = cfg
    invalidate_plugin_help_availability_cache()
    clear_system_prompt_cache()


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_llm_chat_config_reload,
)
get_llm_chat_config = plugin_webui.get
reload_llm_chat_config = plugin_webui.reload
clear_llm_chat_config_cache = plugin_webui.clear_cache
plugin_config = plugin_config_proxy(get_llm_chat_config)
