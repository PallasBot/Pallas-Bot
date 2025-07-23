import time

from nonebot import get_plugin_config, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.rule import Rule
from nonebot.typing import T_State
from ulid import ULID

from src.common.config import GroupConfig, TaskManager
from src.common.db import GroupConfigModule, SingProgress
from src.common.utils import HTTPXClient

from .config import Config
from .ncm import get_song_id, get_song_title

plugin_config = get_plugin_config(Config)

SERVER_URL = f"http://{plugin_config.ai_server_host}:{plugin_config.ai_server_port}"

SPEAKERS = plugin_config.sing_speakers.keys()
SING_CMD = "唱歌"
SING_CONTINUE_CMDS = {"继续唱", "接着唱"}
WHAT_SONG_CMDS = {"什么歌", "哪首歌", "啥歌"}
SING_COOLDOWN_KEY = "sing"
PLAY_COOLDOWN_KEY = "play"
WHAT_SONG_COOLDOWN_KEY = "song_title"


async def is_to_sing(event: GroupMessageEvent, state: T_State) -> bool:
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
    config = GroupConfig(event.group_id, cooldown=120)
    if not await config.is_cooldown(SING_COOLDOWN_KEY):
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

    url = f"{SERVER_URL}{plugin_config.sing_endpoint}/{request_id}"
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
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)
    task_id = response.json().get("task_id", "")
    if not task_id:
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)

    sing_progress = SingProgress(
        song_id=str(song_id),
        chunk_index=chunk_index,
        key=key,
    )
    await config.update_sing_progress(sing_progress)
    await sing_msg.finish("欢呼吧！")


async def is_play(bot: Bot, event: Event, state: T_State) -> bool:
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
    config = GroupConfig(event.group_id, cooldown=10)
    if not await config.is_cooldown(PLAY_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(PLAY_COOLDOWN_KEY)

    speaker = state["speaker"]
    url = f"{SERVER_URL}{plugin_config.play_endpoint}/{speaker}"
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


async def what_song(event: Event) -> bool:
    text = event.get_plaintext()
    return any(text.startswith(spk) for spk in SPEAKERS) and any(key in text for key in WHAT_SONG_CMDS)


song_title_cmd = on_message(
    rule=Rule(what_song),
    priority=12,
    block=True,
    permission=permission.GROUP,
)


@song_title_cmd.handle()
async def _(event: GroupMessageEvent):
    group_id = event.group_id
    config = GroupConfig(group_id, cooldown=10)
    if not await config.is_cooldown(WHAT_SONG_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(WHAT_SONG_COOLDOWN_KEY)

    config_module = await GroupConfig.get_fresh_group_config_module(group_id)
    if not config_module:
        return

    progress = config_module.sing_progress
    if not progress:
        return
    song_title = await get_song_title(progress.song_id)
    if not song_title:
        return

    await song_title_cmd.finish(f"{song_title}")
