"""SMTP 邮件传输与凭据配置（内核共享）。

历史上邮件能力散落在 ``pallas_plugin_bot_status`` 内（``MailConfig`` + ``send_mail`` +
``bot_status_smtp_*`` 配置），导致需要发信的其它插件（如 ``pallas_plugin_who_is_spy``）
反向 import bot_status 插件造成跨插件耦合。此处把「SMTP 传输」与「传输凭据」下沉到内核，
任何插件都从 ``pallas.api.utils`` 取用，互不依赖。

凭据 env 使用中性名 ``PALLAS_SMTP_*``（不再隶属 bot_status 插件）。收件人、离线宽限等
业务字段仍归各插件自身。
"""

from __future__ import annotations

from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from pallas.api.config import field_help, install_hot_reload_config

_SSL_PORT = 465


class MailConfig:
    """一次发信所需的完整参数：传输凭据 + 收件人。"""

    def __init__(self, user: str, password: str, server: str, port: int, notice_email: str):
        self.user = user
        self.password = password
        self.server = server
        self.port = port
        self.notice_email = notice_email

    def check_params(self) -> bool:
        return bool(self.user and self.password and self.server and self.port and self.notice_email)


class SmtpConfig(BaseModel):
    """SMTP 传输凭据（不含收件人，收件人由各业务场景决定）。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    smtp_user: str = Field(
        default="",
        description=field_help("SMTP 发信账号", "通常与发件邮箱一致"),
    )
    smtp_password: str = Field(
        default="",
        description=field_help("SMTP 密码或应用专用授权码", "QQ 邮箱填 SMTP 授权码而非登录密码"),
    )
    smtp_server: str = Field(
        default="",
        description=field_help("SMTP 服务器主机名", "如 smtp.qq.com / smtp.example.com"),
    )
    smtp_port: int = Field(
        default=_SSL_PORT,
        description=field_help("SMTP 端口", "465 多为 SSL，587 多为 STARTTLS"),
    )


# 中性 env 名（凭据已下沉内核，不再隶属 bot_status 插件）。
_SMTP_FIELD_TO_ENV = {
    "smtp_user": "PALLAS_SMTP_USER",
    "smtp_password": "PALLAS_SMTP_PASSWORD",
    "smtp_server": "PALLAS_SMTP_SERVER",
    "smtp_port": "PALLAS_SMTP_PORT",
}

_smtp_handle = install_hot_reload_config(
    SmtpConfig,
    config_module=__name__,
    field_to_env=_SMTP_FIELD_TO_ENV,
)
get_smtp_config = _smtp_handle.get
reload_smtp_config = _smtp_handle.reload
clear_smtp_config_cache = _smtp_handle.clear_cache


def build_mail_config(notice_email: str) -> MailConfig:
    """用当前 SMTP 凭据 + 指定收件人组装 ``MailConfig``。"""
    cfg = get_smtp_config()
    return MailConfig(
        user=cfg.smtp_user,
        password=cfg.smtp_password,
        server=cfg.smtp_server,
        port=cfg.smtp_port,
        notice_email=notice_email,
    )


async def send_mail(title: str, content: str, mail_config: MailConfig) -> str | None:
    """发送邮件通知；成功返回 ``None``，失败返回错误信息字符串。"""
    message = MIMEMultipart("alternative")
    message["Subject"] = Header(title, "utf-8").encode()
    message["From"] = mail_config.user
    message["To"] = mail_config.notice_email
    message.attach(MIMEText(content))

    use_tls = mail_config.port == _SSL_PORT
    try:
        async with aiosmtplib.SMTP(hostname=mail_config.server, port=mail_config.port, use_tls=use_tls) as smtp:
            await smtp.login(mail_config.user, mail_config.password)
            await smtp.send_message(message)
    except Exception as e:
        err = f"mail send failed: {e}"
        logger.error(err)
        return err

    logger.info("mail sent successfully")
    return None
