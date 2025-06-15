import os
import random
import time
from pathlib import Path
from threading import Lock

from nonebot import get_plugin_config, logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment, permission
from nonebot.rule import Rule
from nonebot.typing import T_State

from src.common.config import GroupConfig

from .config import Config
from .ncm import get_song_id, get_song_title

plugin_config = get_plugin_config(Config)

SING_CMD = "唱歌"
SING_CONTINUE_CMDS = ["继续唱", "接着唱"]
SING_COOLDOWN_KEY = "sing"


# TODO: Alconna 改造
async def is_to_sing(event: GroupMessageEvent, state: T_State) -> bool:
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
        progress = GroupConfig(group_id=event.group_id).sing_progress()
        if not progress:
            return False

        song_id = progress["song_id"]
        chunk_index = progress["chunk_index"]
        key_val = progress["key"]
        if not song_id or chunk_index > 100:
            return False
        state["song_id"] = str(song_id)
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
    if not config.is_cooldown(SING_COOLDOWN_KEY):
        return
    config.refresh_cooldown(SING_COOLDOWN_KEY)

    speaker = state["speaker"]
    song_key = state["song_id"]
    song_id = song_key if song_key.isdigit() else await get_song_id(song_key)
    chunk_index = state["chunk_index"]
    key = state["key"]

    async def failed():
        config.reset_cooldown(SING_COOLDOWN_KEY)
        await sing_msg.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")

    async def success(song: Path, spec_index: int = None):
        config.reset_cooldown(SING_COOLDOWN_KEY)
        config.update_sing_progress({
            "song_id": song_id,
            "chunk_index": (spec_index or chunk_index) + 1,
            "key": key,
        })

        msg: Message = MessageSegment.record(file=song)
        await sing_msg.finish(msg)

    # 下载 -> 切片 -> 人声分离 -> 音色转换（SVC） -> 混音
    # 其中 人声分离和音色转换是吃 GPU 的，所以要加锁，不然显存不够用
    await sing_msg.send("欢呼吧！")

    if not song_id:
        logger.error("get_song_id failed", song_key, song_id)
        await failed()


# 随机放歌（bushi
async def play_song(bot: Bot, event: Event, state: T_State) -> bool:
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
    rule=Rule(play_song),
    priority=13,
    block=False,
    permission=permission.GROUP,
)


@play_cmd.handle()
async def _(bot: Bot, event: Event, state: T_State):
    config = GroupConfig(event.group_id, cooldown=10)
    if not config.is_cooldown("music"):
        return
    config.refresh_cooldown("music")

    speaker = state["speaker"]
    rand_music = get_random_song(speaker)
    if not rand_music:
        return

    msg: Message = MessageSegment.record(file=Path(rand_music))
    await play_cmd.finish(msg)


async def what_song(bot: Bot, event: Event, state: T_State) -> bool:
    text = event.get_plaintext()
    return any([text.startswith(spk) for spk in plugin_config.sing_speakers.keys()]) and any(
        key in text for key in ["什么歌", "哪首歌", "啥歌"]
    )


song_title_cmd = on_message(rule=Rule(what_song), priority=13, block=True, permission=permission.GROUP)


@song_title_cmd.handle()
async def _(bot: Bot, event: Event, state: T_State):
    config = GroupConfig(event.group_id, cooldown=10)
    progress = config.sing_progress()
    if not progress:
        return

    if not config.is_cooldown("song_title"):
        return
    config.refresh_cooldown("song_title")

    song_id = progress["song_id"]
    song_title = await get_song_title(song_id)
    if not song_title:
        return

    await song_title_cmd.finish(f"{song_title}")
