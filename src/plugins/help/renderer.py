import hashlib
import io
from pathlib import Path

import pillowmd
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.matcher import Matcher
from PIL import Image

from .styles import get_default_style


def resize_image_if_needed(image, max_width=1200, max_height=2000):
    """调整图像大小"""
    if image.width > max_width or image.height > max_height:
        ratio = min(max_width / image.width, max_height / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        return image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def convert_image_to_bytes(image) -> io.BytesIO:
    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG", optimize=True, compress_level=6)
    img_bytes.seek(0)
    return img_bytes


def get_cache_path(markdown_content: str, style_name: str, group_id: int = None) -> Path:
    """根据markdown内容和群id生成本地路径"""
    if group_id is not None:
        cache_dir = Path("data/help") / str(group_id)
    else:
        cache_dir = Path("data/help") / "private"

    cache_dir.mkdir(parents=True, exist_ok=True)

    content_hash = hashlib.md5(f"{markdown_content}_{style_name}".encode()).hexdigest()
    return cache_dir / f"{content_hash}.png"


def load_cached_image(markdown_content: str, style_name: str, group_id: int = None) -> bytes | None:
    """从本地加载图片"""
    cache_path = get_cache_path(markdown_content, style_name, group_id)
    if cache_path.exists():
        return cache_path.read_bytes()
    return None


def save_image_to_cache(image_data: bytes, markdown_content: str, style_name: str, group_id: int = None) -> None:
    """将图片保存到本地"""
    cache_path = get_cache_path(markdown_content, style_name, group_id)
    cache_path.write_bytes(image_data)


async def _render_markdown(
    markdown_content: str, style_name: str, available_styles: dict
) -> tuple[io.BytesIO, Image.Image]:
    """核心渲染函数"""
    default_style_name = get_default_style(None)
    style = available_styles.get(style_name, available_styles.get(default_style_name, pillowmd.MdStyle()))

    # 获取渲染结果
    render_result = await pillowmd.MdToImage(markdown_content, style=style)
    image = render_result.image

    image = resize_image_if_needed(image)

    img_bytes = convert_image_to_bytes(image)

    return img_bytes, image


async def render_markdown_to_image(
    markdown_content: str, style_name: str, available_styles: dict, group_id: int = None
) -> bytes:
    # 首先尝试从本地加载图片
    cached_image = load_cached_image(markdown_content, style_name, group_id)
    if cached_image:
        return cached_image

    # 如果缓存中没有，则渲染图片
    img_bytes, _ = await _render_markdown(markdown_content, style_name, available_styles)
    image_data = img_bytes.getvalue()

    # 保存到缓存
    save_image_to_cache(image_data, markdown_content, style_name, group_id)

    return image_data


async def send_markdown_as_image(
    markdown_content: str, style_name: str, available_styles: dict, matcher: Matcher, group_id: int = None
) -> None:
    # 获取缓存的图片或渲染新图片
    image_data = await render_markdown_to_image(markdown_content, style_name, available_styles, group_id)
    await matcher.finish(MessageSegment.image(image_data))
