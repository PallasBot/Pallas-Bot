from pathlib import Path

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.shared.utils import HTTPXClient

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

GREETING_DIR = plugin_data_dir("greeting")


def bot_dir(bot_id: int) -> Path:
    d = GREETING_DIR / str(bot_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def download_image(url: str) -> tuple[bytes, str]:
    response = await HTTPXClient.get(url)
    if response is None:
        raise RuntimeError("图片下载失败")
    content_type = response.headers.get("content-type", "")
    ext = ".png" if "png" in content_type else ".jpg"
    return response.content, ext


def clear_welcome_files(bot_dir_path: Path) -> None:
    for name in ("friend_welcome.txt", "friend_welcome.jpg", "friend_welcome.png"):
        f = bot_dir_path / name
        if f.exists():
            f.unlink()


async def user_is_group_admin_or_owner(bot_id: int, group_id: int, user_id: int) -> bool:
    info = await get_bot(str(bot_id)).call_api(
        "get_group_member_info",
        user_id=user_id,
        group_id=group_id,
        no_cache=False,
    )
    return info.get("role") in ("admin", "owner")


def group_welcome_dir(bot_id: int, group_id: int) -> Path:
    d = GREETING_DIR / str(bot_id) / str(group_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_group_welcome_files(group_dir: Path) -> None:
    for name in ("group_welcome.txt", "group_welcome.jpg", "group_welcome.png"):
        f = group_dir / name
        if f.exists():
            f.unlink()


async def get_custom_group_welcome_message(bot_id: int, group_id: int) -> Message | None:
    group_dir = GREETING_DIR / str(bot_id) / str(group_id)
    if not group_dir.exists():
        return None

    msg = Message()

    text_file = group_dir / "group_welcome.txt"
    if text_file.exists():
        content = text_file.read_text(encoding="utf-8").strip()
        if content:
            msg.append(MessageSegment.text(content))

    for ext in (".jpg", ".png"):
        img_file = group_dir / f"group_welcome{ext}"
        if img_file.exists():
            msg.append(MessageSegment.image(img_file.read_bytes()))
            break

    return msg or None


async def get_custom_friend_welcome_message(bot_id: int) -> Message | None:
    bot_dir_path = GREETING_DIR / str(bot_id)
    if not bot_dir_path.exists():
        return None

    msg = Message()

    text_file = bot_dir_path / "friend_welcome.txt"
    if text_file.exists():
        content = text_file.read_text(encoding="utf-8").strip()
        if content:
            msg.append(MessageSegment.text(content))

    for ext in (".jpg", ".png"):
        img_file = bot_dir_path / f"friend_welcome{ext}"
        if img_file.exists():
            msg.append(MessageSegment.image(img_file.read_bytes()))
            break

    return msg or None
