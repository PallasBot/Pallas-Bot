import time
from typing import Annotated

from arclet.alconna import Alconna, Args, Arparma
from nepattern import BasePattern
from nonebot import get_plugin_config, on_message, require
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.params import Depends
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot_plugin_alconna import AlconnaMatches, on_alconna
from ulid import ULID

from src.common.config import GroupConfig, TaskManager
from src.common.db import SingProgress
from src.common.utils import HTTPXClient

from .config import Config
from .ncm import get_song_id, get_song_title

require("nonebot_plugin_alconna")

plugin_config = get_plugin_config(Config)

SERVER_URL = f"http://{plugin_config.ai_server_host}:{plugin_config.ai_server_port}"

SPEAKERS = plugin_config.sing_speakers.keys()
SING_COOLDOWN_KEY = "sing"


sing_alc = Alconna(
    "{speaker:str}唱歌",
    Args["song_id_str", str]["key", BasePattern("(?:0|-?(?:[1-9]|1[0-2]))"), "0"],
)


async def is_to_sing(command: Annotated[Arparma, Depends(AlconnaMatches)], state: T_State) -> bool:
    speaker = command.header["speaker"]
    if speaker not in SPEAKERS:
        return False
    state["speaker"] = plugin_config.sing_speakers[speaker]
    state["song_id"] = command.query("song_id_str")
    state["key"] = command.query("key")
    return True


sing_cmd = on_alconna(
    command=sing_alc,
    rule=Rule(is_to_sing),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@sing_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    config = GroupConfig(event.group_id, cooldown=120)
    if not await config.is_cooldown(SING_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(SING_COOLDOWN_KEY)
    speaker = state["speaker"]
    song_id = await get_song_id(state["song_id"])
    if not song_id:
        await sing_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
    key = int(state["key"])
    chunk_index = 0
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "start_time": time.time(),
        },
    )

    url = f"{SERVER_URL}{plugin_config.sing_endpoint}/{request_id}"
    response = await HTTPXClient.post(
        url,
        json={
            "speaker": speaker,
            "song_id": song_id,
            "chunk_index": chunk_index,
            "key": key,
        },
    )
    if not response:
        await sing_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)
    task_id = response.json().get("task_id", "")
    if not task_id:
        await sing_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)

    sing_progress = SingProgress(
        song_id=song_id,
        chunk_index=chunk_index,
        key=key,
    )
    await config.update_sing_progress(sing_progress)
    await sing_cmd.finish("欢呼吧！")


sing_continue_alc = Alconna("{speaker:str}re:((接着)|(继续))唱")


async def is_sing_continue(command: Annotated[Arparma, Depends(AlconnaMatches)], state: T_State) -> bool:
    speaker = command.header["speaker"]
    if speaker not in SPEAKERS:
        return False
    state["speaker"] = plugin_config.sing_speakers[speaker]
    return True


sing_continue_cmd = on_alconna(
    command=sing_continue_alc,
    rule=Rule(is_sing_continue),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@sing_continue_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    config = GroupConfig(event.group_id, cooldown=120)
    if not await config.is_cooldown(SING_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(SING_COOLDOWN_KEY)

    speaker = state["speaker"]
    progress = await config.sing_progress()
    if not progress:
        await sing_continue_cmd.finish()

    song_id = progress.song_id
    chunk_index = progress.chunk_index
    key = progress.key
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "start_time": time.time(),
        },
    )

    url = f"{SERVER_URL}{plugin_config.sing_endpoint}/{request_id}"
    response = await HTTPXClient.post(
        url,
        json={
            "speaker": speaker,
            "song_id": song_id,
            "chunk_index": chunk_index,
            "key": key,
        },
    )
    if not response:
        await sing_continue_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)
    task_id = response.json().get("task_id", "")
    if not task_id:
        await sing_continue_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
        await TaskManager.remove_task(request_id)

    progress.chunk_index += 1
    await config.update_sing_progress(progress)
    await sing_cmd.finish("欢呼吧！")


play_alc = Alconna("{speaker:str}唱歌")


async def is_play(command: Annotated[Arparma, Depends(AlconnaMatches)], state: T_State) -> bool:
    speaker = command.header["speaker"]
    if speaker not in SPEAKERS:
        return False
    state["speaker"] = plugin_config.sing_speakers[speaker]
    return True


play_cmd = on_alconna(
    command=play_alc,
    rule=Rule(is_play),
    permission=permission.GROUP,
    priority=11,
    block=False,
)


@play_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    config = GroupConfig(event.group_id, cooldown=10)
    if not await config.is_cooldown("music"):
        return
    await config.refresh_cooldown("music")

    speaker = state["speaker"]
    url = f"{SERVER_URL}{plugin_config.play_endpoint}/{speaker}"
    response = await HTTPXClient.get(url)
    if not response:
        await sing_continue_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")
    task_id = response.json().get("task_id", "")
    if not task_id:
        await sing_continue_cmd.finish("我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。")

    await TaskManager.add_task(
        task_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "start_time": time.time(),
        },
    )
    await sing_cmd.finish("欢呼吧！")


async def what_song(event: Event) -> bool:
    text = event.get_plaintext()
    return any(text.startswith(spk) for spk in SPEAKERS) and any(key in text for key in ["什么歌", "哪首歌", "啥歌"])


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
    if not progress:
        return

    if not config.is_cooldown("song_title"):
        return
    await config.refresh_cooldown("song_title")

    song_title = await get_song_title(progress.song_id)
    if not song_title:
        return

    await song_title_cmd.finish(f"{song_title}")
