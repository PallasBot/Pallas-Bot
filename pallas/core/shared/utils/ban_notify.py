"""自动拉黑事件通知：QQ 私聊号主/超管 → 全失败且已配邮箱时邮件兜底。

私聊复用 request_handler 的 notify_admins（号主始终通知 + 可选超管）；邮件走
内核 pallas.api.utils.send_mail（PALLAS_SMTP_* + smtp_notice_email），未配
SMTP 或收件邮箱时静默跳过。通知带封禁原因与最近触发消息样例。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

if TYPE_CHECKING:
    from nonebot.adapters import Bot


async def notify_auto_ban(
    bot: Bot,
    *,
    title: str,
    reason: str,
    samples: list[str],
    group_id: int,
    user_id: int,
) -> None:
    body_qq = (
        f"[自动拉黑] {title}\n用户 {user_id} 在群 {group_id}（{reason}）已自动群内拉黑。\n"
        f"如误伤可用「牛牛解禁 {user_id}」恢复。"
    )
    if samples:
        body_qq += "\n最近触发消息：\n" + "\n".join(f"  - {s}" for s in samples[:3])
    from packages.request_handler.runtime import notify_admins as _notify_admins

    delivered = False
    try:
        delivered = await _notify_admins(
            bot,
            body_qq,
            kind="auto_ban",
            target_id=str(user_id),
        )
    except Exception:
        logger.warning(
            "auto ban notify (private) failed for bot=[{}] group=[{}] user=[{}]",
            bot.self_id,
            group_id,
            user_id,
        )
    if delivered:
        return
    # 私聊全失败 → 邮件兜底（未配置 SMTP/收件邮箱则忽略）
    try:
        from pallas.api.utils import build_mail_config, send_mail
        from pallas.core.shared.utils.mail import get_smtp_config

        notice_email = get_smtp_config().smtp_notice_email
        if not notice_email:
            return
        mail_cfg = build_mail_config(notice_email)
        if not mail_cfg.check_params():
            return
        body_mail = (
            f"Bot {bot.self_id} 在群 {group_id} 自动拉黑用户 {user_id}：{reason}\n可用「牛牛解禁 {user_id}」恢复。"
        )
        if samples:
            body_mail += "\n最近触发消息：\n" + "\n".join(f"  - {s}" for s in samples[:3])
        await send_mail(title, body_mail, mail_cfg)
    except Exception:
        logger.warning(
            "auto ban notify (mail) failed for bot=[{}] group=[{}] user=[{}]",
            bot.self_id,
            group_id,
            user_id,
        )
