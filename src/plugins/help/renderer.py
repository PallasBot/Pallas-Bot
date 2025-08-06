import io

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


async def render_markdown_to_image(markdown_content: str, style_name: str, available_styles: dict) -> bytes:
    img_bytes, _ = await _render_markdown(markdown_content, style_name, available_styles)
    return img_bytes.getvalue()


async def send_markdown_as_image(
    markdown_content: str, style_name: str, available_styles: dict, matcher: Matcher
) -> None:
    img_bytes, _ = await _render_markdown(markdown_content, style_name, available_styles)
    await matcher.finish(MessageSegment.image(img_bytes))
