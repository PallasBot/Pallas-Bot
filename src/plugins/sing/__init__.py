import time

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State
from ulid import ULID

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, SCENE_PRIVATE, join_usage, usage_line
from src.foundation.config import GroupConfig, TaskManager
from src.foundation.db import SingProgress
from src.shared.utils import HTTPXClient

from .config import get_sing_config, sing_server_url
from .ncm_login import get_song_id, get_song_title

__plugin_meta__ = PluginMetadata(
    name="牛牛唱歌",
    description="群内 AI 翻唱、点歌与续唱。",
    usage=join_usage(
        usage_line("牛牛唱歌 〈歌曲名〉 [key=±N]", "AI 翻唱，可调音调"),
        usage_line("牛牛继续唱 / 牛牛接着唱", "续唱上一首"),
        usage_line("牛牛点歌 〈歌曲名〉", "播放网易云原曲"),
        usage_line("牛牛什么歌 / 牛牛哪首歌 / 牛牛啥歌", "查询当前曲目"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "sing.ncm_login", "label": "网易云登录", "default": "superuser"},
            {"id": "sing.ncm_logout", "label": "网易云登出", "default": "superuser"},
        ],
        "menu_data": [
            {
                "func": "牛牛唱歌",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛唱歌 歌曲名 [key=±N]",
                "brief_des": "AI 翻唱指定歌曲",
                "detail_des": "按歌名搜索并翻唱，可用 key=±N 调音；每段约 120 秒。",
            },
            {
                "func": "继续唱",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛继续唱 / 牛牛接着唱",
                "brief_des": "继续上次未完成的歌曲",
                "detail_des": "继续播放上次未完成的歌曲的下一个片段。",
            },
            {
                "func": "点歌",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛点歌 歌曲名",
                "brief_des": "播放网易云原曲",
                "detail_des": "在vip有效的情况下优先播放vip歌曲",
            },
            {
                "func": "牛牛什么歌",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛什么歌 / 牛牛哪首歌 / 牛牛啥歌",
                "brief_des": "查询当前播放的歌曲名",
                "detail_des": "查询牛牛当前正在演唱的歌曲名称。",
            },
            {
                "func": "网易云登录",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "网易云登录 / 网易云登出",
                "command_permissions": ["sing.ncm_login", "sing.ncm_logout"],
                "brief_des": "绑定或解绑网易云",
                "detail_des": "私聊按提示完成登录或登出，用于点歌 VIP 等能力。",
            },
        ],
    },
)

SING_CMD = "唱歌"
REQUEST_SONG_CMD = "点歌"
SING_CONTINUE_CMDS = {"继续唱", "接着唱"}
WHAT_SONG_CMDS = {"什么歌", "哪首歌", "啥歌"}
SING_COOLDOWN_KEY = "sing"
PLAY_COOLDOWN_KEY = "play"
REQUEST_SONG_COOLDOWN_KEY = "request_song"
WHAT_SONG_COOLDOWN_KEY = "song_title"


async def finish_on_cooldown(matcher, config: GroupConfig, cooldown_key: str) -> bool:
    if await config.is_cooldown(cooldown_key):
        return True
    await matcher.finish("牛牛还在回味上一首，稍等再点歌吧。")
    return False


async def is_to_sing(event: GroupMessageEvent, state: T_State) -> bool:
    plugin_config = get_sing_config()
    if not plugin_config.sing_enable:
        return False
    text = event.get_plaintext()
    if not text:
        return False

    if SING_CMD not in text and not any(cmd in text for cmd in SING_CONTINUE_CMDS):
        return False

    if text.endswith(SING_CMD):
        return False

    has_spk = False
    for name, speaker in plugin_config.sing_speakers.items():
        if not text.startswith(name):
            continue
        text = text.replace(name, "").strip()
        has_spk = True
        state["speaker"] = speaker
        break

    if not has_spk:
        return False

    if "key=" in text:
        key_pos = text.find("key=")
        key_val = text[key_pos + 4 :].strip()  # 获取key=后面的值
        text = text.replace("key=" + key_val, "")  # 去掉消息中的key信息
        try:
            key_int = int(key_val)  # 判断输入的key是不是整数
            if key_int < -12 or key_int > 12:
                return False  # 限制一下key的大小，一个八度应该够了
        except ValueError:
            return False
    else:
        key_val = 0
    state["key"] = key_val

    if text.startswith(SING_CMD):
        song_key = text.replace(SING_CMD, "").strip()
        if not song_key:
            return False
        state["song_id"] = song_key
        state["chunk_index"] = 0
        return True

    if text in SING_CONTINUE_CMDS:
        progress = await GroupConfig(group_id=event.group_id).sing_progress()
        logger.info(f"bot [{event.self_id}] sing continue read progress in group [{event.group_id}]: {progress}")
        if not progress:
            return False

        song_id = str(progress.song_id)
        chunk_index = progress.chunk_index + 1
        key_val = progress.key
        if not song_id or chunk_index > 100:
            return False
        state["song_id"] = song_id
        state["chunk_index"] = chunk_index
        state["key"] = key_val
        return True

    return False


sing_msg = on_message(
    rule=Rule(is_to_sing),
    priority=5,
    block=True,
    permission=permission.GROUP,
)


@sing_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    plugin_config = get_sing_config()
    config = GroupConfig(event.group_id, cooldown=10)
    if not await finish_on_cooldown(sing_msg, config, SING_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(SING_COOLDOWN_KEY)
    speaker = state["speaker"]
    song_id = await get_song_id(state["song_id"])
    if not song_id:
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
    key = state["key"]
    chunk_index = state["chunk_index"]
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "task_type": "sing",
            "start_time": time.time(),
        },
    )

    url = f"{sing_server_url(plugin_config)}{plugin_config.sing_endpoint}/{request_id}"
    response = await HTTPXClient.post(
        url,
        json={
            "speaker": speaker,
            "song_id": song_id,
            "sing_length": plugin_config.sing_length,
            "chunk_index": chunk_index,
            "key": key,
        },
    )
    if not response:
        await TaskManager.remove_task(request_id)
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
    task_id = response.json().get("task_id", "")
    if not task_id:
        await TaskManager.remove_task(request_id)
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")

    if chunk_index == 0:
        await config.update_sing_progress(
            SingProgress(
                song_id=str(song_id),
                chunk_index=chunk_index,
                key=key,
            )
        )
    await sing_msg.finish("欢呼吧！")


async def is_play(bot: Bot, event: Event, state: T_State) -> bool:
    plugin_config = get_sing_config()
    text = event.get_plaintext()
    if not text or not text.endswith(SING_CMD):
        return False

    for name, speaker in plugin_config.sing_speakers.items():
        if not text.startswith(name):
            continue
        state["speaker"] = speaker
        return True

    return False


play_cmd = on_message(
    rule=Rule(is_play),
    permission=permission.GROUP,
    priority=11,
    block=False,
)


@play_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    plugin_config = get_sing_config()
    config = GroupConfig(event.group_id, cooldown=10)
    if not await finish_on_cooldown(play_cmd, config, PLAY_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(PLAY_COOLDOWN_KEY)

    speaker = state["speaker"]
    url = f"{sing_server_url(plugin_config)}{plugin_config.play_endpoint}/{speaker}"
    response = await HTTPXClient.get(url)
    if not response:
        await play_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
    task_id = response.json().get("task_id", "")
    if not task_id:
        await play_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")

    await TaskManager.add_task(
        task_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "task_type": "play",
            "start_time": time.time(),
        },
    )
    await play_cmd.finish("欢呼吧！")


async def is_to_request_song(event: GroupMessageEvent, state: T_State) -> bool:
    plugin_config = get_sing_config()
    if not plugin_config.sing_enable:
        return False
    text = event.get_plaintext()
    if not text:
        return False

    if REQUEST_SONG_CMD not in text:
        return False

    if not text.endswith(REQUEST_SONG_CMD):
        has_spk = False
        for name, speaker in plugin_config.sing_speakers.items():
            if not text.startswith(name):
                continue
            text = text.replace(name, "").strip()
            has_spk = True
            state["speaker"] = speaker
            break

        if not has_spk:
            return False

        if text.startswith(REQUEST_SONG_CMD):
            song_name = text.replace(REQUEST_SONG_CMD, "").strip()
            if not song_name:
                return False
            state["song_name"] = song_name
            return True

    return False


request_song_msg = on_message(
    rule=Rule(is_to_request_song),
    priority=5,
    block=True,
    permission=permission.GROUP,
)


@request_song_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    plugin_config = get_sing_config()
    config = GroupConfig(event.group_id, cooldown=10)
    if not await finish_on_cooldown(request_song_msg, config, REQUEST_SONG_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(REQUEST_SONG_COOLDOWN_KEY)

    song_name = state["song_name"]

    song_id = await get_song_id(song_name)
    if not song_id:
        return False

    request_id = str(ULID())
    url = f"{sing_server_url(plugin_config)}{plugin_config.request_endpoint}/{request_id}"

    response = await HTTPXClient.post(
        url,
        json={
            "song_id": song_id,
        },
    )
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "task_type": "request",
            "start_time": time.time(),
        },
    )

    if not response:
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)
    task_id = response.json().get("task_id", "")
    if not task_id:
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)

    await sing_msg.finish("欢呼吧！")


async def what_song(event: Event) -> bool:
    text = event.get_plaintext()
    speakers = get_sing_config().sing_speakers.keys()
    return any(text.startswith(spk) for spk in speakers) and any(key in text for key in WHAT_SONG_CMDS)


song_title_cmd = on_message(
    rule=Rule(what_song),
    priority=12,
    block=True,
    permission=permission.GROUP,
)


@song_title_cmd.handle()
async def _(event: GroupMessageEvent):
    config = GroupConfig(event.group_id, cooldown=10)
    progress = await config.sing_progress()
    logger.info(f"bot [{event.self_id}] sing song title query in group [{event.group_id}]: {progress}")

    if not progress:
        return
    if not await config.is_cooldown(WHAT_SONG_COOLDOWN_KEY):
        return

    await config.refresh_cooldown(WHAT_SONG_COOLDOWN_KEY)
    song_title = await get_song_title(progress.song_id)
    if not song_title:
        return

    await song_title_cmd.finish(f"{song_title}")
