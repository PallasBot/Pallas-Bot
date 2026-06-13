from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config
from src.console.webui.field_help import field_help


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = Field(
        default="127.0.0.1",
        description=field_help(
            "点歌/唱歌服务所在机器的地址",
            "本机填 127.0.0.1；服务在别的机器上填其 IP 或域名",
        ),
    )
    ai_server_port: int = Field(
        default=9099,
        description=field_help(
            "点歌/唱歌服务监听的端口",
            "填整数，需与后端实际监听端口一致",
        ),
    )
    sing_enable: bool = Field(
        default=False,
        description=field_help(
            "是否启用唱歌与播放相关命令",
            "开启前请确认后端服务已部署且地址正确",
        ),
    )
    sing_endpoint: str = Field(
        default="/api/sing",
        description=field_help(
            "提交合成任务的接口路径",
            "以 / 开头的路径，会拼在「主机:端口」后面",
            "须与后端文档一致",
        ),
    )
    play_endpoint: str = Field(
        default="/api/play",
        description=field_help(
            "触发或获取播放的接口路径",
            "以 / 开头；留空或错误会导致播放失败",
        ),
    )
    request_endpoint: str = Field(
        default="/api/request",
        description=field_help(
            "唱歌排队请求的接口路径",
            "通用配置页「服务网关」主要使用此项做连通检测",
        ),
    )
    sing_length: int = Field(default=120, description="单次合成音频的默认最大时长（秒），具体以后端为准。")
    sing_speakers: dict[str, str] = Field(
        default_factory=lambda: {
            "帕拉斯": "pallas",
            "牛牛": "pallas",
        },
        description="唱歌的音色映射",
    )


def on_sing_config_reload(cfg: Config) -> None:
    from src.plugins.help.plugin_availability import invalidate_plugin_help_availability_cache

    invalidate_plugin_help_availability_cache()


plugin_webui = install_hot_reload_config(Config, config_module=__name__, on_reload=on_sing_config_reload)
get_sing_config = plugin_webui.get
reload_sing_config = plugin_webui.reload
clear_sing_config_cache = plugin_webui.clear_cache


def sing_server_url(cfg: Config | None = None) -> str:
    c = cfg or get_sing_config()
    return f"http://{c.ai_server_host}:{c.ai_server_port}"
