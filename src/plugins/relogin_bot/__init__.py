import asyncio
import base64
from datetime import datetime
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, PrivateMessageEvent
from nonebot.params import ArgPlainText, CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from src.common.config import BotConfig
from src.common.db import make_bot_config_repository
from src.plugins.pallas_protocol import manager as protocol_manager

__plugin_meta__ = PluginMetadata(
    name="牛牛重新上号",
    description="为指定 QQ 账号重启协议端并推送登录二维码。",
    usage="""
牛牛重新上号 <QQ号>
示例：牛牛重新上号 3879348674
""".strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "重新上号",
                "trigger_method": "on_cmd",
                "trigger_condition": "牛牛重新上号 <QQ号>",
                "brief_des": "重启账号并回传二维码",
                "detail_des": "自动重启协议端账号，等待二维码文件生成并在私聊推送。",
            },
        ],
    },
)

relogin_cmd = on_command("牛牛重新上号", priority=5, block=True)


async def _is_bot_admin(bot: Bot, event: MessageEvent) -> bool:
    try:
        admins = await BotConfig(int(bot.self_id))._find("admins")
        return int(event.get_user_id()) in admins
    except Exception:
        return False


async def _bot_id_exists_in_db(bot_id: int) -> bool:
    try:
        repo = make_bot_config_repository()
        return await repo.get(bot_id) is not None
    except Exception:
        return False


def _extract_qq(arg: str) -> str:
    text = (arg or "").strip()
    return text if text.isdigit() else ""


async def _wait_qrcode(account_data_dir: Path, since: datetime, timeout_sec: int = 60) -> Path | None:
    qr_path = account_data_dir / "cache" / "qrcode.png"
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        if qr_path.is_file():
            try:
                mtime = datetime.fromtimestamp(qr_path.stat().st_mtime, tz=since.tzinfo)
                if mtime >= since:
                    return qr_path
            except OSError:
                pass
        await asyncio.sleep(1.2)
    return None


@relogin_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not isinstance(event, PrivateMessageEvent):
        await relogin_cmd.finish("请私聊使用该命令。")
    if not (await _is_bot_admin(bot, event) or await SUPERUSER(bot, event)):
        await relogin_cmd.finish("你不是该牛牛管理员，无法执行重新上号。")

    qq = _extract_qq(args.extract_plain_text())
    if qq:
        relogin_cmd.set_arg("qq", Message(qq))
        return
    await relogin_cmd.send("请回复要重新上号的QQ号：")


@relogin_cmd.got("qq")
async def _(bot: Bot, event: MessageEvent, qq_input: str = ArgPlainText("qq")):
    qq = _extract_qq(qq_input)
    if not qq:
        await relogin_cmd.finish("QQ号格式不正确，请重新执行：牛牛重新上号")
    if not protocol_manager.has_account(qq):
        if not await _bot_id_exists_in_db(int(qq)):
            await relogin_cmd.finish(f"数据库中不存在 bot_id={qq}，请先完成牛牛创建流程。")
        try:
            protocol_manager.create_account({"qq": qq, "enabled": True})
            await bot.send(event, f"未找到账号 {qq}，已自动创建并继续上号流程。")
        except Exception as e:
            await relogin_cmd.finish(f"未找到账号且自动创建失败：{e}")
    account = protocol_manager.get_account(qq) or {}
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not account_data_dir:
        await relogin_cmd.finish("账号目录缺失，无法执行重新上号。")

    await bot.send(event, f"开始为账号 {qq} 重新上号，正在重启协议端...")
    started_at = datetime.now().astimezone()
    try:
        await protocol_manager.restart_account(qq)
    except Exception as e:
        await relogin_cmd.finish(f"重启失败：{e}")

    qr_path = await _wait_qrcode(account_data_dir, started_at)
    if qr_path is None:
        await relogin_cmd.finish(
            "已完成重启，但在 60 秒内未检测到新的二维码文件。\n"
            "可去协议端管理页查看实时日志，或稍后重试。"
        )

    try:
        encoded = base64.b64encode(qr_path.read_bytes()).decode()
        await bot.send(event, "重启完成，请使用下面二维码登录：")
        await bot.send(event, Message(f"[CQ:image,file=base64://{encoded}]"))
    except OSError as e:
        await relogin_cmd.finish(f"二维码读取失败：{e}")
