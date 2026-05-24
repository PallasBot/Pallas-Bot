from typing import Literal

from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config

StatusListModeSetting = Literal["auto", "session", "fleet", "connected"]


class Config(BaseModel, extra="ignore"):
    bot_status_smtp_user: str = Field(default="", description="SMTP 发信账号（通常与发件邮箱一致）。")
    bot_status_smtp_password: str = Field(default="", description="SMTP 密码或应用专用授权码。")
    bot_status_smtp_server: str = Field(default="", description="SMTP 服务器主机名，如 smtp.example.com。")
    bot_status_smtp_port: int = Field(default=465, description="SMTP 端口；465 多为 SSL，587 多为 STARTTLS。")
    bot_status_notice_email: str = Field(default="", description="接收 Bot 状态告警（如掉线）的收件人邮箱。")
    bot_status_offline_grace_time: int = Field(
        default=30,
        description="判定为离线并发送邮件通知前，允许无心跳的宽限时间（分钟）。",
    )
    bot_status_list_mode: StatusListModeSetting = Field(
        default="auto",
        description=(
            "牛牛在吗名册：auto=分片 fleet、单进程 session；"
            "session=本 worker 连接；fleet=协议 enabled+registry；"
            "connected=全集群曾连 WS（不含 registry 幽灵号）。"
        ),
    )


class MailConfig:
    def __init__(self, user: str, password: str, server: str, port: int, notice_email: str):
        self.user = user
        self.password = password
        self.server = server
        self.port = port
        self.notice_email = notice_email

    def check_params(self) -> bool:
        return bool(self.user and self.password and self.server and self.port and self.notice_email)


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_bot_status_config = plugin_webui.get
reload_bot_status_config = plugin_webui.reload
clear_bot_status_config_cache = plugin_webui.clear_cache
