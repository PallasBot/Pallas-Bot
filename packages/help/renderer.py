import hashlib
import io
import time
from pathlib import Path

import pillowmd
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.matcher import Matcher
from PIL import Image

from pallas.core.foundation.paths import plugin_data_dir, project_path

from .pillowmd_bold import apply_help_light_bold_patch
from .styles import get_default_style

apply_help_light_bold_patch()

_STYLE_SUFFIX_TTL_SEC = 60.0
_style_suffix_cache: tuple[float, str] = (0.0, "")
_HELP_CACHE_FILES_PER_DIR_MAX = 20


def invalidate_help_image_cache_suffix() -> None:
    global _style_suffix_cache
    _style_suffix_cache = (0.0, "")
    from pallas.console.webui.plugin_package_assets import invalidate_plugin_package_assets_revision

    invalidate_plugin_package_assets_revision()


def _help_style_files_revision() -> str:
    """样式目录内 setting/elements 变更时使帮助图缓存失效。"""
    from .config import get_help_config

    cfg = get_help_config()
    parts: list[str] = []
    for style_cfg in cfg.default_styles or []:
        style_dir = project_path(style_cfg.path)
        for filename in (
            "setting.yml",
            "setting.json",
            "elements.yml",
            "elements.json",
            "style.py",
        ):
            path = style_dir / filename
            if not path.is_file():
                continue
            try:
                parts.append(f"{filename}:{int(path.stat().st_mtime)}")
            except OSError:
                parts.append(f"{filename}:0")
    return ";".join(parts) if parts else "none"


def _compute_help_image_cache_suffix() -> str:
    from .config import get_help_config
    from .help_theme import resolve_help_font_path

    cfg = get_help_config()
    font_path = resolve_help_font_path()
    font_part = f"font={font_path.name}:0"
    try:
        if font_path.is_file():
            font_part = f"font={font_path.name}:{int(font_path.stat().st_mtime)}"
    except OSError:
        pass
    base = (
        f"spaint={int(cfg.side_paint_enabled)}"
        f"|fn={cfg.side_paint_filename}"
        f"|sc={cfg.side_paint_scale:.4f}"
        f"|ap={int(cfg.side_paint_auto_page)}"
        f"|enc=v3"
        f"|{font_part}"
        f"|sty={_help_style_files_revision()}"
    )
    from pallas.console.webui.plugin_package_assets import plugin_package_assets_revision

    base = f"{base}|{plugin_package_assets_revision()}"
    if not cfg.side_paint_enabled:
        return base
    paint_path = project_path("resource", "styles", "default", "imgs") / cfg.side_paint_filename
    if not paint_path.is_file():
        return base
    try:
        paint_mtime = int(paint_path.stat().st_mtime)
    except OSError:
        paint_mtime = 0
    return f"{base}|pm={paint_mtime}"


def _help_image_cache_suffix() -> str:
    now = time.monotonic()
    global _style_suffix_cache
    cached_at, cached = _style_suffix_cache
    if cached and now - cached_at < _STYLE_SUFFIX_TTL_SEC:
        return cached
    suffix = _compute_help_image_cache_suffix()
    _style_suffix_cache = (now, suffix)
    return suffix


def resize_image_if_needed(image, max_width=1200, max_height=2800):
    """调整图像大小"""
    if image.width > max_width or image.height > max_height:
        ratio = min(max_width / image.width, max_height / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        return image.resize(new_size, Image.Resampling.LANCZOS)
    return image


# NapCat 等协议端对超大 base64 图片经 WS 发送不稳定；控制原始体积
_HELP_IMAGE_MAX_SEND_BYTES = 2_500_000
_HELP_IMAGE_MIN_SIDE = 360


def encode_help_image_for_send(image: Image.Image) -> bytes:
    """将帮助图编码为可经 OneBot base64 发送的字节串；过大时缩小或转 JPEG。"""
    work = image
    png_bytes = _png_bytes(work)
    if len(png_bytes) <= _HELP_IMAGE_MAX_SEND_BYTES:
        return png_bytes

    orig_w, orig_h = work.size
    scale = 0.82
    while len(png_bytes) > _HELP_IMAGE_MAX_SEND_BYTES:
        w, h = work.size
        if min(w, h) <= _HELP_IMAGE_MIN_SIDE:
            break
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        work = work.resize((nw, nh), Image.Resampling.LANCZOS)
        png_bytes = _png_bytes(work)

    if len(png_bytes) <= _HELP_IMAGE_MAX_SEND_BYTES:
        logger.warning(
            "help image shrunk for upload orig={}x{} final={}x{} bytes={}",
            orig_w,
            orig_h,
            work.width,
            work.height,
            len(png_bytes),
        )
        return png_bytes

    rgba = work.convert("RGBA")
    rgb = Image.new("RGB", rgba.size, (255, 255, 255))
    rgb.paste(rgba, mask=rgba.split()[-1])

    for quality in (85, 75, 65, 55):
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg_bytes = buf.getvalue()
        if len(jpeg_bytes) <= _HELP_IMAGE_MAX_SEND_BYTES:
            logger.warning(
                "help image encoded as JPEG q={} after shrink orig={}x{} final={}x{} bytes={}",
                quality,
                orig_w,
                orig_h,
                work.width,
                work.height,
                len(jpeg_bytes),
            )
            return jpeg_bytes

    logger.warning(
        "help image still large after JPEG fallback bytes={} (may fail on protocol)",
        len(jpeg_bytes),
    )
    return jpeg_bytes


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()


def get_cache_path(markdown_content: str, style_name: str, group_id: int | None = None) -> Path:
    """根据markdown内容和群id生成本地路径"""
    help_data_dir = plugin_data_dir("help")
    if group_id is not None:
        cache_dir = help_data_dir / str(group_id)
    else:
        cache_dir = help_data_dir / "private"

    cache_dir.mkdir(parents=True, exist_ok=True)

    content_hash = hashlib.md5(f"{markdown_content}_{style_name}_{_help_image_cache_suffix()}".encode()).hexdigest()
    return cache_dir / f"{content_hash}.png"


def load_cached_image(markdown_content: str, style_name: str, group_id: int | None = None) -> bytes | None:
    """从本地加载图片"""
    cache_path = get_cache_path(markdown_content, style_name, group_id)
    if cache_path.exists():
        return cache_path.read_bytes()
    return None


def save_image_to_cache(image_data: bytes, markdown_content: str, style_name: str, group_id: int | None = None) -> None:
    """将图片保存到本地"""
    cache_path = get_cache_path(markdown_content, style_name, group_id)
    cache_path.write_bytes(image_data)
    _prune_help_cache_dir(cache_path.parent, keep=_HELP_CACHE_FILES_PER_DIR_MAX, current=cache_path)


def _prune_help_cache_dir(cache_dir: Path, *, keep: int, current: Path) -> None:
    if keep < 1:
        keep = 1
    try:
        pngs = [p for p in cache_dir.glob("*.png") if p.is_file()]
    except OSError:
        return
    if len(pngs) <= keep:
        return

    def _sort_key(path: Path) -> tuple[int, str]:
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        return (mtime_ns, path.name)

    try:
        current_resolved = current.resolve()
    except OSError:
        current_resolved = current
    survivors = {current_resolved}
    remaining = keep - 1
    if remaining > 0:
        for path in sorted(pngs, key=_sort_key, reverse=True):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved == current_resolved:
                continue
            survivors.add(resolved)
            remaining -= 1
            if remaining == 0:
                break
    for path in pngs:
        try:
            if path.resolve() not in survivors:
                path.unlink(missing_ok=True)
        except OSError:
            continue


async def _render_markdown(
    markdown_content: str, style_name: str, available_styles: dict
) -> tuple[io.BytesIO, Image.Image]:
    """核心渲染函数"""
    default_style_name = get_default_style(None)
    style = available_styles.get(style_name, available_styles.get(default_style_name, pillowmd.MdStyle()))
    from .config import get_help_config

    help_cfg = get_help_config()

    paint_arg = None
    auto_page = False
    if help_cfg.side_paint_enabled:
        paint_dir = project_path("resource", "styles", "default", "imgs")
        pillowmd.Setting.PAINT_PATH = paint_dir
        paint_path = paint_dir / help_cfg.side_paint_filename
        if paint_path.is_file():
            with Image.open(paint_path) as opened:
                pil = opened.convert("RGBA")
            sc = help_cfg.side_paint_scale
            if sc > 0 and sc != 1.0:
                nw = max(1, int(pil.width * sc))
                nh = max(1, int(pil.height * sc))
                pil = pil.resize((nw, nh), Image.Resampling.LANCZOS)
            # 传 Image 时库仍会在 tys>300 且 tys<txs*2.5 时按正文高度再缩放立绘
            paint_arg = pil
        else:
            paint_arg = help_cfg.side_paint_filename
        auto_page = help_cfg.side_paint_auto_page

    render_result = await pillowmd.MdToImage(
        markdown_content,
        style=style,
        paint=paint_arg,
        autoPage=auto_page,
    )
    image = render_result.image

    image = resize_image_if_needed(image)

    encoded = encode_help_image_for_send(image)
    img_bytes = io.BytesIO(encoded)

    return img_bytes, image


async def render_markdown_to_image(
    markdown_content: str, style_name: str, available_styles: dict, group_id: int | None = None
) -> bytes:
    # 首先尝试从本地加载图片
    cached_image = load_cached_image(markdown_content, style_name, group_id)
    if cached_image:
        if len(cached_image) > _HELP_IMAGE_MAX_SEND_BYTES:
            with Image.open(io.BytesIO(cached_image)) as im:
                fixed = encode_help_image_for_send(im.convert("RGBA"))
            save_image_to_cache(fixed, markdown_content, style_name, group_id)
            return fixed
        return cached_image

    # 如果缓存中没有，则渲染图片
    img_bytes, _ = await _render_markdown(markdown_content, style_name, available_styles)
    image_data = img_bytes.getvalue()

    # 保存到缓存
    save_image_to_cache(image_data, markdown_content, style_name, group_id)

    return image_data


async def render_v3_image_bytes(
    cache_key: str,
    image: Image.Image,
    *,
    group_id: int | None,
    style_name: str,
) -> bytes:
    cached = load_cached_image(cache_key, style_name, group_id)
    if cached:
        if len(cached) > _HELP_IMAGE_MAX_SEND_BYTES:
            with Image.open(io.BytesIO(cached)) as im:
                fixed = encode_help_image_for_send(im.convert("RGBA"))
            save_image_to_cache(fixed, cache_key, style_name, group_id)
            return fixed
        return cached

    work = resize_image_if_needed(image)
    encoded = encode_help_image_for_send(work.convert("RGBA"))
    save_image_to_cache(encoded, cache_key, style_name, group_id)
    return encoded


async def send_plugin_menu_image(
    menu_rows: list,
    *,
    show_ignored: bool,
    matcher: Matcher,
    group_id: int | None = None,
    page: int = 1,
    total_pages: int = 1,
    total_plugin_count: int | None = None,
    total_enabled_count: int | None = None,
) -> None:
    image_data = await render_plugin_menu_to_image(
        menu_rows,
        show_ignored=show_ignored,
        group_id=group_id,
        page=page,
        total_pages=total_pages,
        total_plugin_count=total_plugin_count,
        total_enabled_count=total_enabled_count,
    )
    await matcher.finish(MessageSegment.image(image_data))


def menu_image_cache_key(
    menu_rows: list,
    *,
    show_ignored: bool,
    page: int,
    total_pages: int,
    total_plugin_count: int,
) -> str:
    row_parts = [f"{row.index}:{row.display_name}:{int(row.enabled)}" for row in menu_rows]
    parts = [
        f"menu_v1|ignored={int(show_ignored)}|page={page}/{total_pages}|total={total_plugin_count}",
        f"suffix={_help_image_cache_suffix()}",
        *row_parts,
    ]
    return "|".join(parts)


async def render_plugin_menu_to_image(
    menu_rows: list,
    *,
    show_ignored: bool,
    group_id: int | None = None,
    page: int = 1,
    total_pages: int = 1,
    total_plugin_count: int | None = None,
    total_enabled_count: int | None = None,
) -> bytes:
    from .draw_plugin_menu import draw_plugin_menu_image

    total_count = total_plugin_count if total_plugin_count is not None else len(menu_rows)
    enabled_count = (
        total_enabled_count if total_enabled_count is not None else sum(1 for row in menu_rows if row.enabled)
    )
    cache_key = menu_image_cache_key(
        menu_rows,
        show_ignored=show_ignored,
        page=page,
        total_pages=total_pages,
        total_plugin_count=total_count,
    )
    image = draw_plugin_menu_image(
        menu_rows,
        show_ignored=show_ignored,
        page=page,
        total_pages=total_pages,
        total_plugin_count=total_count,
        total_enabled_count=enabled_count,
    )
    return await render_v3_image_bytes(cache_key, image, group_id=group_id, style_name="menu_v1")


async def send_plugin_detail_image(
    data,
    *,
    matcher: Matcher,
    group_id: int | None = None,
) -> None:
    from .draw_plugin_detail import draw_plugin_detail_image

    cache_key = (
        f"plugin_v1|{data.display_name}|enabled={data.enabled}|funcs={len(data.functions)}"
        f"|suffix={_help_image_cache_suffix()}"
    )
    image = draw_plugin_detail_image(data)
    image_data = await render_v3_image_bytes(cache_key, image, group_id=group_id, style_name="detail_v1")
    await matcher.finish(MessageSegment.image(image_data))


async def send_function_detail_image(
    data,
    *,
    matcher: Matcher,
    group_id: int | None = None,
) -> None:
    from .draw_function_detail import draw_function_detail_image

    cache_key = f"function_v1|{data.display_name}|{data.index}/{data.total}|{data.func_name}|suffix={_help_image_cache_suffix()}"  # noqa: E501
    image = draw_function_detail_image(data)
    image_data = await render_v3_image_bytes(cache_key, image, group_id=group_id, style_name="detail_v1")
    await matcher.finish(MessageSegment.image(image_data))


async def send_markdown_as_image(
    markdown_content: str, style_name: str, available_styles: dict, matcher: Matcher, group_id: int | None = None
) -> None:
    image_data = await render_markdown_to_image(markdown_content, style_name, available_styles, group_id)
    await matcher.finish(MessageSegment.image(image_data))
