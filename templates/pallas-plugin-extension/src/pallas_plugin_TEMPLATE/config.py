from pydantic import BaseModel, Field

from pallas.api.config import install_hot_reload_config


class Config(BaseModel, extra="ignore"):
    template_enable: bool = Field(
        default=True,
        description="模板开关。",
        # WebUI 表单标签：不写中文 label 时控制台显示英文键名
        json_schema_extra={"label": "模板开关"},
    )


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
