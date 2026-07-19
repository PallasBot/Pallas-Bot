"""平台侧媒体解析（参考图下载等）。"""

from .draw_reference import draw_reference_download_options
from .reference_resolve import (
    ReferenceDownloadOptions,
    ReferenceResolveResult,
    bytes_from_reference_token,
    bytes_to_data_reference_url,
    decode_inline_image_reference,
    is_inline_reference_token,
    is_platform_reference_url,
    reference_token_to_bytes,
    resolve_reference_inline_urls,
)

__all__ = [
    "draw_reference_download_options",
    "ReferenceDownloadOptions",
    "ReferenceResolveResult",
    "bytes_from_reference_token",
    "bytes_to_data_reference_url",
    "decode_inline_image_reference",
    "is_inline_reference_token",
    "is_platform_reference_url",
    "reference_token_to_bytes",
    "resolve_reference_inline_urls",
]
