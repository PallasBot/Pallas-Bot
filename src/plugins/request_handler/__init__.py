import json
from pathlib import Path

from nonebot import on_command, on_request
from nonebot.adapters.onebot.v11 import Bot, FriendRequestEvent, GroupRequestEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER, Permission
from nonebot.plugin import PluginMetadata

from src.common.config import BotConfig, GroupConfig, UserConfig
from src.plugins.help.plugin_manager import is_plugin_disabled

__plugin_meta__ = PluginMetadata(
    name="申请管理",
    description="处理好友申请与入群邀请，通知管理员并支持手动审批",
    usage="""
查看好友申请 - 查看所有待处理的好友申请
同意好友 <QQ号> - 同意待处理的好友申请
同意所有好友 - 同意所有待处理的好友申请
查看入群邀请 - 查看所有待处理的入群邀请
同意入群 <群号> - 同意待处理的入群邀请
同意所有入群 - 同意所有待处理的入群邀请
拒绝入群 <群号> - 拒绝待处理的入群邀请
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "1.0.0",
        "menu_data": [
            {
                "func": "查看待处理申请",
                "trigger_method": "on_cmd",
                "trigger_condition": "查看好友申请 / 查看入群邀请",
                "brief_des": "查看所有待处理的好友申请或入群邀请",
                "detail_des": "由牛牛管理员执行，列出当前所有待处理的好友申请或入群邀请",
            },
            {
                "func": "好友申请审批",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意好友 <QQ号>",
                "brief_des": "同意待处理的好友申请",
                "detail_des": "由牛牛管理员执行，同意指定 QQ 号的好友申请",
            },
            {
                "func": "批量审批",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意所有好友 / 同意所有入群",
                "brief_des": "批量同意所有待处理申请",
                "detail_des": "由牛牛管理员执行，一次性同意所有待处理的好友申请或入群邀请",
            },
            {
                "func": "入群邀请审批",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意入群/拒绝入群 <群号>",
                "brief_des": "同意或拒绝待处理的入群邀请",
                "detail_des": "由牛牛管理员执行，同意或拒绝指定群的入群邀请",
            },
            {
                "func": "通知开关",
                "trigger_method": "on_cmd",
                "trigger_condition": "牛牛开启/关闭 request_handler",
                "brief_des": "控制申请通知是否推送给管理员",
                "detail_des": "通过 help 控制好友申请和入群邀请的通知推送",
            },
        ],
        "menu_template": "default",
    },
)

DATA_DIR = Path("data/request_handler")
DATA_DIR.mkdir(parents=True, exist_ok=True)

FRIEND_REQ_FILE = DATA_DIR / "pending_friend_requests.json"
GROUP_REQ_FILE = DATA_DIR / "pending_group_requests.json"

PLUGIN_NAME = "request_handler"


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# {bot_id: {user_id: flag}}
pending_friend: dict[str, dict[str, str]] = load_json(FRIEND_REQ_FILE)
# {bot_id: {group_id: {...}}}
pending_group: dict[str, dict[str, dict]] = load_json(GROUP_REQ_FILE)


async def get_nickname(bot: Bot, user_id: int) -> str:
    try:
        info = await bot.call_api("get_stranger_info", user_id=user_id)
        return info.get("nickname", str(user_id))
    except Exception:
        return str(user_id)


async def get_group_name(bot: Bot, group_id: int) -> str:
    try:
        info = await bot.call_api("get_group_info", group_id=group_id)
        return info.get("group_name", str(group_id))
    except Exception:
        pass
    try:
        sys_msg = await bot.call_api("get_group_system_msg")
        all_reqs = (sys_msg.get("join_requests") or []) + (sys_msg.get("invited_requests") or [])
        for req in all_reqs:
            if req.get("group_id") == group_id:
                name = req.get("group_name", "")
                if name:
                    return name
    except Exception:
        pass
    return str(group_id)


request_cmd = on_request(priority=14, block=False)

list_friends_cmd = on_command("查看好友申请", priority=5, block=True)
approve_friend_cmd = on_command("同意好友", priority=5, block=True)
approve_all_friends_cmd = on_command("同意所有好友", priority=5, block=True)
list_groups_cmd = on_command("查看入群邀请", priority=5, block=True)
approve_group_cmd = on_command("同意入群", priority=5, block=True)
approve_all_groups_cmd = on_command("同意所有入群", priority=5, block=True)
reject_group_cmd = on_command("拒绝入群", priority=5, block=True)


async def is_bot_admin(bot: Bot, event: MessageEvent) -> bool:
    admins = await BotConfig(int(bot.self_id))._find("admins")
    return event.user_id in admins


BOT_ADMIN = Permission(is_bot_admin)
PERM = SUPERUSER | BOT_ADMIN


async def notify_admins(bot: Bot, msg: str) -> None:
    admins = await BotConfig(int(bot.self_id))._find("admins")
    for admin_id in admins:
        try:
            await bot.send_private_msg(user_id=admin_id, message=msg)
        except Exception:
            pass


@request_cmd.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    bot_id = int(bot.self_id)
    bot_key = str(bot_id)
    pending_friend.setdefault(bot_key, {})[str(event.user_id)] = event.flag
    save_json(FRIEND_REQ_FILE, pending_friend)

    if not await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id):
        nickname = await get_nickname(bot, event.user_id)
        msg = (
            f"[好友申请]\n"
            f"申请人：{nickname}（{event.user_id}）\n"
            f"验证消息：{event.comment or '（无）'}\n"
            f"同意：同意好友 {event.user_id}\n"
            f"发送同意所有好友可以批量同意\n"
            f"发送查看好友申请可以查看所有待处理的好友申请"
        )
        await notify_admins(bot, msg)

    if await BotConfig(bot_id).auto_accept():
        await event.approve(bot)
        pending_friend.get(bot_key, {}).pop(str(event.user_id), None)
        save_json(FRIEND_REQ_FILE, pending_friend)


@list_friends_cmd.handle()
async def handle_list_friends(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    if not bot_pending:
        await list_friends_cmd.finish("当前没有待处理的好友申请")
    lines = [f"待处理好友申请（共 {len(bot_pending)} 条）："]
    for uid in bot_pending.keys():
        nickname = await get_nickname(bot, int(uid))
        lines.append(f"  {nickname}（{uid}）")
    lines.append("发送 同意好友 <QQ号> 或 同意所有好友 来审批")
    await list_friends_cmd.finish("\n".join(lines))


@approve_friend_cmd.handle()
async def handle_approve_friend(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_friend_cmd.finish("请输入正确的QQ号，例如：同意好友 123456")

    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    flag = bot_pending.get(arg)
    if not flag:
        nickname = await get_nickname(bot, int(arg))
        await approve_friend_cmd.finish(f"未找到来自 {nickname}（{arg}）的待处理好友申请")

    await bot.set_friend_add_request(flag=flag, approve=True)
    bot_pending.pop(arg, None)
    save_json(FRIEND_REQ_FILE, pending_friend)
    nickname = await get_nickname(bot, int(arg))
    await approve_friend_cmd.finish(f"已同意 {nickname}（{arg}）的好友申请")


@list_groups_cmd.handle()
async def handle_list_groups(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await list_groups_cmd.finish("当前没有待处理的入群邀请")
    lines = [f"待处理入群邀请（共 {len(bot_pending)} 条）："]
    for group_key, req in bot_pending.items():
        nickname = await get_nickname(bot, req["user_id"])
        group_name = await get_group_name(bot, int(group_key))
        lines.append(f"  {group_name}（{group_key}）← {nickname}（{req['user_id']}）邀请")
    lines.append("发送 同意入群 <群号> / 拒绝入群 <群号> 或 同意所有入群 来审批")
    await list_groups_cmd.finish("\n".join(lines))


@request_cmd.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    if event.sub_type == "invite":
        if await GroupConfig(event.group_id).is_banned() or await UserConfig(event.user_id).is_banned():
            await event.reject(bot)
            return

        bot_id = int(bot.self_id)
        bot_key = str(bot_id)
        group_key = str(event.group_id)
        pending_group.setdefault(bot_key, {})[group_key] = {
            "flag": event.flag,
            "sub_type": "invite",
            "user_id": event.user_id,
            "group_id": event.group_id,
            "comment": event.comment or "",
        }
        save_json(GROUP_REQ_FILE, pending_group)

        if not await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id):
            nickname = await get_nickname(bot, event.user_id)
            group_name = await get_group_name(bot, event.group_id)
            msg = (
                f"[入群邀请]\n"
                f"邀请人：{nickname}（{event.user_id}）\n"
                f"群：{group_name}（{event.group_id}）\n"
                f"同意：同意入群 {event.group_id}\n"
                f"拒绝：拒绝入群 {event.group_id}\n"
                f"发送同意所有入群可以批量同意"
            )
            await notify_admins(bot, msg)

        bot_config = BotConfig(bot_id)
        if await bot_config.auto_accept() or await bot_config.is_admin_of_bot(event.user_id):
            await event.approve(bot)
            pending_group.get(bot_key, {}).pop(group_key, None)
            save_json(GROUP_REQ_FILE, pending_group)


@approve_all_friends_cmd.handle()
async def handle_approve_all_friends(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    if not bot_pending:
        await approve_all_friends_cmd.finish("当前没有待处理的好友申请")
    ok, fail = 0, 0
    for uid, flag in list(bot_pending.items()):
        try:
            await bot.set_friend_add_request(flag=flag, approve=True)
            bot_pending.pop(uid, None)
            ok += 1
        except Exception:
            fail += 1
    save_json(FRIEND_REQ_FILE, pending_friend)
    await approve_all_friends_cmd.finish(f"已同意 {ok} 个好友申请" + (f"，{fail} 个失败" if fail else ""))


@approve_all_groups_cmd.handle()
async def handle_approve_all_groups(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await approve_all_groups_cmd.finish("当前没有待处理的入群邀请")
    ok, fail = 0, 0
    for key, req in list(bot_pending.items()):
        try:
            await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
            bot_pending.pop(key, None)
            ok += 1
        except Exception:
            fail += 1
    save_json(GROUP_REQ_FILE, pending_group)
    await approve_all_groups_cmd.finish(f"已同意 {ok} 个入群邀请" + (f"，{fail} 个失败" if fail else ""))


@approve_group_cmd.handle()
async def handle_approve_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_group_cmd.finish("格式：同意入群 <群号>")

    bot_key = str(bot.self_id)
    group_id = int(arg)
    group_key = str(group_id)
    bot_pending = pending_group.get(bot_key, {})
    req = bot_pending.get(group_key)
    if not req:
        group_name = await get_group_name(bot, group_id)
        await approve_group_cmd.finish(f"未找到群 {group_name}（{group_id}）的待处理入群邀请")

    try:
        await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
    except Exception as e:
        bot_pending.pop(group_key, None)
        save_json(GROUP_REQ_FILE, pending_group)
        await approve_group_cmd.finish(f"操作失败（请求可能已过期或被处理）：{e}")
        return
    bot_pending.pop(group_key, None)
    save_json(GROUP_REQ_FILE, pending_group)
    nickname = await get_nickname(bot, req["user_id"])
    group_name = await get_group_name(bot, group_id)
    await approve_group_cmd.finish(f"已同意 {nickname}（{req['user_id']}）的入群邀请:{group_name}({group_id})")


@reject_group_cmd.handle()
async def handle_reject_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await reject_group_cmd.finish("格式：拒绝入群 <群号>")

    bot_key = str(bot.self_id)
    group_id = int(arg)
    group_key = str(group_id)
    bot_pending = pending_group.get(bot_key, {})
    req = bot_pending.get(group_key)
    if not req:
        group_name = await get_group_name(bot, group_id)
        await reject_group_cmd.finish(f"未找到群 {group_name}（{group_id}）的待处理入群邀请")

    try:
        await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=False)
    except Exception as e:
        bot_pending.pop(group_key, None)
        save_json(GROUP_REQ_FILE, pending_group)
        await reject_group_cmd.finish(f"操作失败（请求可能已过期或被处理）：{e}")
        return
    bot_pending.pop(group_key, None)
    save_json(GROUP_REQ_FILE, pending_group)
    nickname = await get_nickname(bot, req["user_id"])
    group_name = await get_group_name(bot, group_id)
    await reject_group_cmd.finish(f"已拒绝 {nickname}（{req['user_id']}）的入群邀请:{group_name}({group_id})")
