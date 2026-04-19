import asyncio
import random
from pathlib import Path

from nonebot import get_bot, get_plugin_config, on_command, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    FriendAddNoticeEvent,
    GroupAdminNoticeEvent,
    GroupBanNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PokeNotifyEvent,
    PrivateMessageEvent,
    permission,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule, to_me
from nonebot.typing import T_State

from src.common.config import BotConfig, GroupConfig, UserConfig
from src.common.utils import HTTPXClient, is_bot_admin
from src.plugins.help.plugin_manager import is_plugin_disabled

from .config import Config
from .voice import get_random_voice, get_voice_filepath

__plugin_meta__ = PluginMetadata(
    name="牛牛群欢迎",
    description="处理群变动信息以及支持自定义好友欢迎消息",
    usage="""
设置好友欢迎 - 设置自定义好友欢迎消息（文本/图片/图文混合）
清除好友欢迎 - 清除已设置的好友欢迎消息
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "入群欢迎",
                "trigger_method": "on_notice",
                "trigger_condition": "群成员增加通知",
                "brief_des": "新成员入群时发送欢迎消息",
                "detail_des": "牛牛作为群管理员时，新成员入群自动发送欢迎语；牛牛自己入群时也会自我介绍",
            },
            {
                "func": "好友欢迎",
                "trigger_method": "on_notice",
                "trigger_condition": "好友添加通知",
                "brief_des": "新好友添加时发送欢迎消息",
                "detail_des": "新好友添加后自动发送自定义欢迎消息（若已设置）",
            },
            {
                "func": "设置好友欢迎",
                "trigger_method": "on_cmd",
                "trigger_condition": "设置好友欢迎",
                "brief_des": "设置自定义好友欢迎消息",
                "detail_des": "由牛牛管理员在私聊中执行，支持文本、图片或图文混合",
            },
            {
                "func": "清除好友欢迎",
                "trigger_method": "on_cmd",
                "trigger_condition": "清除好友欢迎",
                "brief_des": "清除已设置的好友欢迎消息",
                "detail_des": "由牛牛管理员在私聊中执行",
            },
            {
                "func": "被踢自动拉黑",
                "trigger_method": "on_notice",
                "trigger_condition": "群成员减少通知（kick_me）",
                "brief_des": "被踢出群时自动拉黑该群及操作人",
                "detail_des": "可通过配置 enable_kick_ban=false 关闭此功能",
            },
            {
                "func": "长时间禁言自动退群",
                "trigger_method": "on_notice",
                "trigger_condition": "群禁言通知（ban，目标为牛牛）",
                "brief_des": "被禁言超过 36 小时时自动退群",
                "detail_des": "禁言时长超过 36 小时则自动调用退群接口",
            },
        ],
        "menu_template": "default",
    },
)

plugin_config = get_plugin_config(Config)

operator = "Pallas"
greeting_voices = [
    "交谈1",
    "交谈2",
    "交谈3",
    "晋升后交谈1",
    "晋升后交谈2",
    "信赖提升后交谈1",
    "信赖提升后交谈2",
    "信赖提升后交谈3",
    "闲置",
    "干员报到",
    "精英化晋升1",
    "编入队伍",
    "任命队长",
    "戳一下",
    "信赖触摸",
    "问候",
]

target_msgs = {"牛牛", "帕拉斯"}

GREETING_DIR = Path("data/greeting")


def _bot_dir(bot_id: int) -> Path:
    d = GREETING_DIR / str(bot_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _download_image(url: str) -> tuple[bytes, str]:
    response = await HTTPXClient.get(url)
    if response is None:
        raise RuntimeError("图片下载失败")
    content_type = response.headers.get("content-type", "")
    ext = ".png" if "png" in content_type else ".jpg"
    return response.content, ext


def _clear_welcome_files(bot_dir: Path) -> None:
    """删除该 bot 目录下所有欢迎消息文件。"""
    for name in ("friend_welcome.txt", "friend_welcome.jpg", "friend_welcome.png"):
        f = bot_dir / name
        if f.exists():
            f.unlink()


async def get_custom_friend_welcome_message(bot_id: int) -> Message | None:
    """读取自定义好友欢迎消息，无内容时返回 None。"""
    bot_dir = GREETING_DIR / str(bot_id)
    if not bot_dir.exists():
        return None

    msg = Message()

    text_file = bot_dir / "friend_welcome.txt"
    if text_file.exists():
        content = text_file.read_text(encoding="utf-8").strip()
        if content:
            msg.append(MessageSegment.text(content))

    for ext in (".jpg", ".png"):
        img_file = bot_dir / f"friend_welcome{ext}"
        if img_file.exists():
            msg.append(MessageSegment.image(img_file.read_bytes()))
            break  # 只取第一张

    return msg or None


set_friend_welcome = on_command(
    "设置好友欢迎",
    permission=permission.PRIVATE,
    priority=10,
    block=True,
)


@set_friend_welcome.handle()
async def handle_set_friend_welcome(bot: Bot, event: PrivateMessageEvent, state: T_State):
    if not await BotConfig(event.self_id).is_admin_of_bot(event.user_id):
        await set_friend_welcome.finish("你没有权限执行此操作")
    await set_friend_welcome.send("请发送你想要设置的好友欢迎消息（可以是文本、图片或图文混合）：")
    state["bot_id"] = event.self_id


@set_friend_welcome.got("message")
async def handle_friend_welcome_message(bot: Bot, event: PrivateMessageEvent, state: T_State):
    bot_id: int = state["bot_id"]
    message = event.get_message()
    images = [seg for seg in message if seg.type == "image"]
    text_parts = [seg.data.get("text", "").strip() for seg in message if seg.type == "text"]
    text_content = "\n".join(p for p in text_parts if p)

    if not images and not text_content:
        await set_friend_welcome.reject("欢迎消息不能为空，请重新发送（可以是文本或图片）：")

    d = _bot_dir(bot_id)
    _clear_welcome_files(d)

    if text_content:
        (d / "friend_welcome.txt").write_text(text_content, encoding="utf-8")

    if images:
        image_url = images[0].data.get("url") or images[0].data.get("file", "")
        if not image_url:
            await set_friend_welcome.reject("无法获取图片链接，请重新发送：")
        try:
            data, ext = await _download_image(image_url)
            (d / f"friend_welcome{ext}").write_bytes(data)
        except Exception as e:
            await set_friend_welcome.reject(f"图片下载失败：{e}\n请重新发送：")

    parts = []
    if text_content:
        parts.append("文本")
    if images:
        parts.append("图片")
    label = "＋".join(parts)
    await set_friend_welcome.finish(f"好友欢迎消息（{label}）已设置成功！")


clear_friend_welcome = on_command(
    "清除好友欢迎",
    permission=permission.PRIVATE,
    priority=10,
    block=True,
)


@clear_friend_welcome.handle()
async def handle_clear_friend_welcome(bot: Bot, event: PrivateMessageEvent):
    if not await BotConfig(event.self_id).is_admin_of_bot(event.user_id):
        await clear_friend_welcome.finish("你没有权限执行此操作")

    d = GREETING_DIR / str(event.self_id)
    if not d.exists():
        await clear_friend_welcome.finish("未设置自定义好友欢迎消息")

    before = list(d.glob("friend_welcome*"))
    _clear_welcome_files(d)
    after = list(d.glob("friend_welcome*"))

    if len(before) > len(after):
        await clear_friend_welcome.finish("好友欢迎消息已清除！")
    else:
        await clear_friend_welcome.finish("未设置自定义好友欢迎消息")


async def message_equal(event: GroupMessageEvent) -> bool:
    raw_msg = event.raw_message
    if raw_msg not in target_msgs:
        return False
    return not await is_plugin_disabled("greeting", event.group_id, event.self_id)


call_me_cmd = on_message(
    rule=Rule(message_equal),
    priority=13,
    block=False,
    permission=permission.GROUP,
)


@call_me_cmd.handle()
async def handle_call_me(bot: Bot, event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_cooldown("call_me"):
        return
    await config.refresh_cooldown("call_me")

    file_path = get_random_voice(operator, greeting_voices)
    if file_path:
        await call_me_cmd.finish(MessageSegment.record(file=file_path.read_bytes()))


to_me_cmd = on_message(
    rule=to_me(),
    priority=14,
    block=False,
    permission=permission.GROUP,
)


@to_me_cmd.handle()
async def handle_to_me(bot: Bot, event: GroupMessageEvent):
    if await is_plugin_disabled("greeting", event.group_id, event.self_id):
        return

    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_cooldown("to_me"):
        return
    await config.refresh_cooldown("to_me")

    if len(event.get_plaintext().strip()) == 0 and not event.reply:
        file_path = get_random_voice(operator, greeting_voices)
        if file_path:
            await to_me_cmd.finish(MessageSegment.record(file=file_path.read_bytes()))


all_notice = on_notice(priority=13, block=False)

_NoticeEvent = (
    GroupAdminNoticeEvent
    | GroupIncreaseNoticeEvent
    | GroupDecreaseNoticeEvent
    | GroupBanNoticeEvent
    | FriendAddNoticeEvent
    | PokeNotifyEvent
)


@all_notice.handle()
async def handle_notice(event: _NoticeEvent):
    if await is_plugin_disabled("greeting", getattr(event, "group_id", None), event.self_id):
        return

    if event.notice_type == "notify" and event.sub_type == "poke" and event.target_id == event.self_id:
        config = BotConfig(event.self_id, event.group_id)  # type: ignore
        if not await config.is_cooldown("poke"):
            return
        await config.refresh_cooldown("poke")
        await asyncio.sleep(random.randint(1, 3))
        await get_bot(str(event.self_id)).call_api(
            "group_poke",
            group_id=event.group_id,
            user_id=event.user_id,
        )

    elif event.notice_type == "group_increase":
        if event.user_id == event.self_id:
            msg = (
                "我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......"
                "虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。"
            )
        elif await is_bot_admin(event.self_id, event.group_id):
            msg = MessageSegment.at(event.user_id) + MessageSegment.text(
                "博士，欢迎加入这盛大的庆典！我是来自米诺斯的祭司帕拉斯......要来一杯美酒么？"
            )
        else:
            return
        await all_notice.finish(msg)

    elif event.notice_type == "group_admin" and event.sub_type == "set" and event.user_id == event.self_id:
        file_path = get_voice_filepath(operator, "任命助理")
        if file_path:
            await all_notice.finish(MessageSegment.record(file=file_path.read_bytes()))

    elif event.notice_type == "friend_add":
        custom_msg = await get_custom_friend_welcome_message(event.self_id)
        if custom_msg:
            await all_notice.send(custom_msg)
        file_path = get_voice_filepath(operator, "干员报到")
        if file_path:
            await all_notice.finish(MessageSegment.record(file=file_path.read_bytes()))

    elif event.notice_type == "group_ban" and event.sub_type == "ban" and event.user_id == event.self_id:
        if event.duration > 60 * 60 * 36:
            await get_bot(str(event.self_id)).call_api("set_group_leave", group_id=event.group_id)

    elif event.notice_type == "group_decrease" and event.sub_type == "kick_me":
        if plugin_config.enable_kick_ban:
            await GroupConfig(event.group_id).ban()
            await UserConfig(event.operator_id).ban()
