import asyncio
import base64
from datetime import datetime
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, PrivateMessageEvent
from nonebot.params import ArgPlainText, CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.typing import T_State

from src.common.config import BotConfig
from src.common.db import make_bot_config_repository
from src.plugins.pallas_protocol import manager as protocol_manager

__all__ = ["relogin_cmd", "create_cmd"]

__plugin_meta__ = PluginMetadata(
    name="牛牛重新上号",
    description="为指定 QQ 账号重启协议端并推送登录二维码，牛牛管理员可用；超管可创建新牛牛账号。",
    usage="""
牛牛重新上号
创建牛牛
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
                "trigger_condition": "牛牛重新上号 [QQ号]",
                "brief_des": "重启账号并回传二维码（牛牛管理员可用）",
                "detail_des": "自动重启协议端账号，等待二维码文件生成并在私聊推送。",
            },
            {
                "func": "创建牛牛",
                "trigger_method": "on_cmd",
                "trigger_condition": "创建牛牛 [昵称 牛牛QQ 号主QQ ...]",
                "brief_des": "创建并启动新牛牛账号（仅超管）",
                "detail_des": "在协议端创建账号并启动。",
            },
        ],
    },
)

relogin_cmd = on_command("牛牛重新上号", priority=5, block=True)
create_cmd = on_command("创建牛牛", priority=5, block=True, permission=SUPERUSER)

_CANCEL_WORDS = {"取消", "cancel", "退出", "quit"}


async def _is_bot_admin(bot: Bot, event: MessageEvent) -> bool:
    try:
        return await BotConfig(int(bot.self_id)).is_admin_of_bot(int(event.get_user_id()))
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
async def _relogin_handle(event: MessageEvent, state: T_State, args: Message = CommandArg()):  # noqa: B008
    if not isinstance(event, PrivateMessageEvent):
        await relogin_cmd.finish("请私聊使用该命令。")

    qq = _extract_qq(args.extract_plain_text())
    if qq:
        state["qq"] = Message(qq)
    else:
        await relogin_cmd.send("请回复要重新上号的QQ号：")


@relogin_cmd.got("qq")
async def _relogin_got_qq(bot: Bot, event: MessageEvent, state: T_State, qq_input: str = ArgPlainText("qq")):  # noqa: B008
    if qq_input.strip() in _CANCEL_WORDS:
        await relogin_cmd.finish("已取消重新上号。")

    qq = _extract_qq(qq_input)
    if not qq:
        await relogin_cmd.reject("QQ号格式不正确，请重新输入：")

    # 检查用户是否是目标 bot 的管理员（或超管）
    is_target_admin = await BotConfig(int(qq)).is_admin_of_bot(int(event.get_user_id()))
    if not (is_target_admin or await SUPERUSER(bot, event)):
        await relogin_cmd.finish(f"你不是 {qq} 的管理员，无法执行重新上号。")

    state["_qq"] = qq

    if protocol_manager.has_account(qq):
        state["_needs_create"] = False
        state["nickname"] = Message("__skip__")
    else:
        if not await _bot_id_exists_in_db(int(qq)):
            await relogin_cmd.finish(f"数据库中不存在账号为：{qq} 的牛牛")
        state["_needs_create"] = True
        await relogin_cmd.send("该账号协议端不存在，请输入牛牛昵称以自动创建：")


@relogin_cmd.got("nickname")
async def _relogin_got_nickname(
    bot: Bot,
    event: MessageEvent,
    state: T_State,
    nickname_input: str = ArgPlainText("nickname"),  # noqa: B008
):
    qq: str = state["_qq"]
    needs_create: bool = state.get("_needs_create", False)

    if needs_create:
        if nickname_input.strip() in _CANCEL_WORDS:
            await relogin_cmd.finish("已取消重新上号。")
        nickname = nickname_input.strip()
        if not nickname:
            await relogin_cmd.reject("昵称不能为空，请重新输入：")
        try:
            protocol_manager.create_account({"qq": qq, "display_name": nickname, "enabled": True})
            await bot.send(event, f"已创建 {nickname} 并继续上号流程。")
        except Exception as e:
            await relogin_cmd.finish(f"自动创建协议端失败：{e}")

    account = protocol_manager.get_account(qq) or {}
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not account_data_dir:
        await relogin_cmd.finish("账号目录缺失，无法执行重新上号。")

    await bot.send(event, "正在启动协议端...")
    started_at = datetime.now().astimezone()
    try:
        await protocol_manager.restart_account(qq)
    except Exception as e:
        await relogin_cmd.finish(f"启动失败：{e}")

    qr_path = await _wait_qrcode(account_data_dir, started_at)
    if qr_path is None:
        await relogin_cmd.finish("已完成启动，但在 60 秒内未检测到新的二维码文件，请寻找牛牛管理员上报情况")

    try:
        encoded = base64.b64encode(qr_path.read_bytes()).decode()
        await bot.send(event, "启动完成，请使用下面二维码登录：")
        await bot.send(event, Message(f"[CQ:image,file=base64://{encoded}]"))
    except OSError as e:
        await relogin_cmd.finish(f"二维码读取失败：{e}")


@create_cmd.handle()
async def _create_handle(event: MessageEvent, state: T_State, args: Message = CommandArg()):  # noqa: B008
    if not isinstance(event, PrivateMessageEvent):
        await create_cmd.finish("请私聊使用该命令。")

    text = args.extract_plain_text().strip()
    if text:
        parts = text.split()
        if len(parts) < 3:  # noqa: PLR2004
            await create_cmd.finish("参数不足，需要：牛牛昵称 牛牛账号 号主账号（至少一个）")
        display_name, qq, *owner_qqs = parts
        if not qq.isdigit() or len(qq) < 5:  # noqa: PLR2004
            await create_cmd.finish("牛牛账号格式不正确")
        invalid = [oq for oq in owner_qqs if not oq.isdigit()]
        if invalid:
            await create_cmd.finish(f"号主账号格式不正确：{'、'.join(invalid)}")
        state["display_name"] = Message(display_name)
        state["qq"] = Message(qq)
        state["owners"] = Message(" ".join(owner_qqs))
        state["_interactive"] = False
        return

    state["_interactive"] = True
    await create_cmd.send("请输入牛牛昵称：")


@create_cmd.got("display_name")
async def _create_got_name(state: T_State, display_name_input: str = ArgPlainText("display_name")):  # noqa: B008
    if display_name_input.strip() in _CANCEL_WORDS:
        await create_cmd.finish("已取消创建牛牛。")
    if not display_name_input.strip():
        await create_cmd.reject("昵称不能为空，请重新输入：")
    if state.get("_interactive"):
        await create_cmd.send("请输入牛牛QQ号：")


@create_cmd.got("qq")
async def _create_got_qq(state: T_State, qq_input: str = ArgPlainText("qq")):  # noqa: B008
    if qq_input.strip() in _CANCEL_WORDS:
        await create_cmd.finish("已取消创建牛牛。")
    qq = qq_input.strip()
    if not qq.isdigit() or len(qq) < 5:  # noqa: PLR2004
        await create_cmd.reject("QQ号格式不正确，请重新输入：")
    if state.get("_interactive"):
        await create_cmd.send("请输入号主QQ号（如有多个用空格分隔）：")


@create_cmd.got("owners")
async def _create_got_owners(
    display_name_input: str = ArgPlainText("display_name"),  # noqa: B008
    qq_input: str = ArgPlainText("qq"),
    owners_input: str = ArgPlainText("owners"),
):
    if owners_input.strip() in _CANCEL_WORDS:
        await create_cmd.finish("已取消创建牛牛。")

    owner_qqs = owners_input.strip().split()
    if not owner_qqs:
        await create_cmd.reject("号主账号不能为空，请重新输入：")

    invalid = [oq for oq in owner_qqs if not oq.isdigit()]
    if invalid:
        await create_cmd.reject(f"号主账号格式不正确：{'、'.join(invalid)}，请重新输入：")

    display_name = display_name_input.strip()
    qq = qq_input.strip()

    try:
        protocol_manager.create_account({"qq": qq, "display_name": display_name, "enabled": True})
    except Exception as e:
        await create_cmd.finish(f"创建账号失败：{e}")

    try:
        await protocol_manager.start_account(qq)
    except Exception as e:
        await create_cmd.finish(f"账号已创建，但启动失败：{e}")

    owner_ids = [int(oq) for oq in owner_qqs]
    try:
        repo = make_bot_config_repository()
        await repo.upsert_field(int(qq), "admins", owner_ids)
    except Exception as e:
        await create_cmd.finish(f"账号已创建并启动，但写入号主失败：{e}")

    owners_str = "、".join(owner_qqs)
    await create_cmd.finish(f"{display_name}：{qq} 已创建并启动。\n号主：{owners_str}")
