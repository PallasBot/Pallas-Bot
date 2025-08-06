import time

from nonebot import get_plugin_config, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State
from ulid import ULID

from src.common.config import GroupConfig, TaskManager
from src.common.db import SingProgress
from src.common.utils import HTTPXClient

from .config import Config
from .ncm_login import get_song_id, get_song_title

__plugin_meta__ = PluginMetadata(
    name="牛牛唱歌",
    description="基于AI的唱歌功能，可以演唱网易云音乐歌曲",
    usage="""
这个插件可以让牛牛演唱歌曲：
1. 唱歌：
    - 发送"[角色名]唱歌 [歌曲名]"让牛牛唱歌，例如"牛牛唱歌 富士山下"、"兔兔唱歌 虚拟"等
    - 可以指定音调："牛牛唱歌 富士山下 key=2" 或 "牛牛唱歌 富士山下 key=-2"
2. 继续唱：
    - 发送"[角色名]继续唱"或"[角色名]接着唱"可以继续上次未完成的歌曲
3. 查询歌曲：
    - 发送"[角色名]什么歌"、"[角色名]哪首歌"或"[角色名]啥歌"可以查询当前播放的歌曲名
4. 播放：
    - 发送"[角色名]唱歌"可以播放唱过的歌
5. 目前支持的角色：
    - 牛牛 兔兔
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters=["~onebot.v11"],
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "牛牛唱歌",
                "trigger_method": "on_message",
                "trigger_condition": "[角色名]唱歌 [歌曲名]",
                "brief_des": "演唱指定歌曲",
                "detail_des": "通过网易云音乐搜索并演唱指定歌曲，支持调节音调（key参数），每个片段大约120秒。",
            },
            {
                "func": "继续唱",
                "trigger_method": "on_message",
                "trigger_condition": "[角色名]继续唱/接着唱",
                "brief_des": "继续上次未完成的歌曲",
                "detail_des": "继续播放上次未完成的歌曲的下一个片段。",
            },
            {
                "func": "牛牛什么歌",
                "trigger_method": "on_message",
                "trigger_condition": "[角色名]什么歌/哪首歌/啥歌",
                "brief_des": "查询当前播放的歌曲名",
                "detail_des": "查询牛牛当前正在演唱的歌曲名称。",
            },
            {
                "func": "播放歌曲",
                "trigger_method": "on_message",
                "trigger_condition": "[角色名]唱歌",
                "brief_des": "开始随机播放唱过的歌。",
                "detail_des": "发送[角色名]唱歌，随机播放一首唱过的歌",
            },
        ],
        "menu_template": "default",
    },
)

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
        group_id = event.group_id
        config_module = await GroupConfig.get_fresh_group_config_module(group_id)
        if not config_module:
            return

        progress = await GroupConfig(group_id=event.group_id).sing_progress()
        print(progress)
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
    config = GroupConfig(event.group_id, cooldown=10)
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
    config = GroupConfig(event.group_id, cooldown=10)
    progress = await config.sing_progress()

    if not progress:
        return
    if not await config.is_cooldown(WHAT_SONG_COOLDOWN_KEY):
        return

    await config.refresh_cooldown(WHAT_SONG_COOLDOWN_KEY)
    song_title = await get_song_title(progress.song_id)
    if not song_title:
        return

    await song_title_cmd.finish(f"{song_title}")
