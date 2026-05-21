from datetime import datetime

from nonebot import logger

from src.common.config import get_bot_admins

from .config import MailConfig, get_bot_status_config
from .utils import send_mail

STATUS_COOLDOWN_KEY: str = "bot_status"


async def get_bot_admin_emails(bot_id: int) -> list[str]:
    """获取牛牛的admins邮箱列表"""
    emails: list[str] = []

    try:
        admins = await get_bot_admins(bot_id)
        if admins:
            emails.extend(f"{admin_id}@qq.com" for admin_id in admins)
    except Exception as e:
        logger.debug(f"bot [{bot_id}] bot_status get_bot_admin_emails failed: {e}")

    return emails


async def notify_bot_offline(bot_id: int, nickname: str, offline_reason: str = "") -> None:
    """通知牛牛离线"""
    cfg = get_bot_status_config()
    admin_emails: list[str] = await get_bot_admin_emails(bot_id)

    mail_config: MailConfig = MailConfig(
        user=cfg.bot_status_smtp_user,
        password=cfg.bot_status_smtp_password,
        server=cfg.bot_status_smtp_server,
        port=cfg.bot_status_smtp_port,
        notice_email=cfg.bot_status_notice_email,
    )

    # 发送邮件通知
    if mail_config.check_params():
        title: str = f"[牛牛不见啦] {nickname} 已离线 "

        reason_info = ""
        if offline_reason:
            reason_info = f"离线原因: {offline_reason}"

        content: str = f"""
{reason_info}

牛牛昵称：{nickname}
牛牛账号：{bot_id}
掉线时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


        """.strip()

        # 发送给配置的邮箱
        result: str | None = await send_mail(title, content, mail_config)
        if result:
            logger.error(f"bot [{bot_id}] offline notification mail failed: {result}")
        else:
            logger.info(f"bot [{bot_id}] offline notification mail sent (notice_email)")

        # 发送给admin邮箱
        for email in admin_emails:
            try:
                admin_mail_config: MailConfig = MailConfig(
                    user=cfg.bot_status_smtp_user,
                    password=cfg.bot_status_smtp_password,
                    server=cfg.bot_status_smtp_server,
                    port=cfg.bot_status_smtp_port,
                    notice_email=email,
                )
                result = await send_mail(title, content, admin_mail_config)
                if result:
                    logger.error(f"bot [{bot_id}] offline mail to admin [{email}] failed: {result}")
                else:
                    logger.info(f"bot [{bot_id}] offline notification mail sent to admin [{email}]")
            except Exception as e:
                logger.error(f"bot [{bot_id}] offline mail to admin [{email}] exception: {e}")
    else:
        logger.warning("bot_status mail skipped: SMTP config incomplete")


async def handle_test_mail_command(bot, event) -> None:
    """处理测试邮件命令"""
    from nonebot.adapters.onebot.v11 import GroupMessageEvent
    from nonebot.matcher import Matcher

    if isinstance(event, GroupMessageEvent):
        from src.common.config import GroupConfig

        config = GroupConfig(group_id=event.group_id, cooldown=10)
        if not await config.is_cooldown(STATUS_COOLDOWN_KEY):
            return
        await config.refresh_cooldown(STATUS_COOLDOWN_KEY)

    cfg = get_bot_status_config()
    mail_config: MailConfig = MailConfig(
        user=cfg.bot_status_smtp_user,
        password=cfg.bot_status_smtp_password,
        server=cfg.bot_status_smtp_server,
        port=cfg.bot_status_smtp_port,
        notice_email=cfg.bot_status_notice_email,
    )

    if not mail_config.check_params():
        missing_params: list[str] = []
        if not cfg.bot_status_smtp_user:
            missing_params.append("bot_status_smtp_user")
        if not cfg.bot_status_smtp_password:
            missing_params.append("bot_status_smtp_password")
        if not cfg.bot_status_smtp_server:
            missing_params.append("bot_status_smtp_server")
        if not cfg.bot_status_notice_email:
            missing_params.append("bot_status_notice_email")

        matcher = Matcher()
        await matcher.finish(f"邮箱配置缺少参数: {', '.join(missing_params)}")
        return

    title: str = "[Test]  这是一封测试邮件"
    content: str = f"""
牛牛在吗？

发送时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Bot ID: {bot.self_id}

如果你收到了这封邮件，证明邮箱配置正确。
    """.strip()

    result: str | None = await send_mail(title, content, mail_config)
    matcher = Matcher()
    if result:
        await matcher.finish(f"测试邮件发送失败: {result}")
    else:
        await matcher.finish("测试邮件发送成功！")
