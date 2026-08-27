"""检测与解析用户消息中的图片（VLM 契约）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import unquote

_CQ_VISION_RE = re.compile(r"\[CQ:(?:image|mface|record)", re.IGNORECASE)
_CQ_VISION_SEGMENT_RE = re.compile(r"\[CQ:(?:image|mface)[^\]]*\]", re.IGNORECASE)
_VISION_HISTORY_PLACEHOLDER = "[图片]"
_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass(frozen=True)
class VisionMessagePayload:
    has_image: bool
    image_urls: tuple[str, ...]
    plain_text: str


def user_message_has_vision_content(text: str) -> bool:
    return bool(_CQ_VISION_RE.search(text or ""))


def strip_vision_segments_for_history(text: str, *, placeholder: str = _VISION_HISTORY_PLACEHOLDER) -> str:
    raw = str(text or "")
    if not user_message_has_vision_content(raw):
        return raw
    plain = _CQ_VISION_SEGMENT_RE.sub(" ", raw)
    plain = re.sub(r"\s+", " ", plain).strip()
    label = (placeholder or _VISION_HISTORY_PLACEHOLDER).strip() or _VISION_HISTORY_PLACEHOLDER
    if plain:
        return f"{label} {plain}".strip()
    return label


def vision_plain_text(text: str) -> str:
    raw = str(text or "")
    if not user_message_has_vision_content(raw):
        return raw.strip()
    plain = _CQ_VISION_SEGMENT_RE.sub(" ", raw)
    return re.sub(r"\s+", " ", plain).strip()


def extract_url_from_cq_segment(segment: str) -> str:
    body = str(segment or "").strip()
    if not body.startswith("[CQ:"):
        return ""
    inner = body[1:-1] if body.endswith("]") else body[1:]
    parts = inner.split(",")
    url = ""
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = unescape(unquote(value.strip()))
        if not value:
            continue
        if key == "url" and _HTTP_URL_RE.match(value):
            return value
        if key == "file" and _HTTP_URL_RE.match(value) and not url:
            url = value
    return url


def extract_vision_message_payload(text: str, *, max_images: int = 3) -> VisionMessagePayload:
    raw = str(text or "")
    segments = _CQ_VISION_SEGMENT_RE.findall(raw)
    if not segments:
        return VisionMessagePayload(has_image=False, image_urls=(), plain_text=raw.strip())

    limit = max(1, int(max_images))
    seen: set[str] = set()
    urls: list[str] = []
    for segment in segments:
        url = extract_url_from_cq_segment(segment)
        if not url:
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
        if len(urls) >= limit:
            break

    plain = vision_plain_text(raw)
    return VisionMessagePayload(
        has_image=bool(segments),
        image_urls=tuple(urls),
        plain_text=plain,
    )


def _segment_type_and_data(segment: object) -> tuple[str, dict[str, str]]:
    """从单条消息段里取出类型与数据字典，兼容 NoneBot MessageSegment 对象与 dict。"""
    import html

    if isinstance(segment, dict):
        seg_type = str(segment.get("type") or "")
        data = segment.get("data") or {}
        raw_data = dict(data) if isinstance(data, dict) else {}
    else:
        seg_type = str(getattr(segment, "type", None) or "")
        raw_data = dict(getattr(segment, "data", None) or {})
    data: dict[str, str] = {}
    for key, value in raw_data.items():
        if isinstance(value, str):
            data[str(key)] = html.unescape(value)
        else:
            data[str(key)] = str(value)
    return seg_type, data


def vision_payload_from_segments(
    segments: object | None,
    *,
    max_images: int = 3,
) -> VisionMessagePayload:
    """从已迭代的消息段(NoneBot Message/MessageSegment 或 get_msg 返回的 dict 列表)提取图片。

    与 extract_vision_message_payload(作用于 CQ 字符串)不同，本函数作用于解析后的消息段，
    用于 event.reply.message 等已被 OneBot 适配器拆分的结构。
    """
    if segments is None:
        return VisionMessagePayload(has_image=False, image_urls=(), plain_text="")
    limit = max(1, int(max_images))
    seen: set[str] = set()
    urls: list[str] = []
    for segment in segments:
        seg_type, data = _segment_type_and_data(segment)
        if seg_type not in {"image", "mface"}:
            continue
        url = str(data.get("url") or "")
        if not url.startswith(("http://", "https://")):
            file_value = str(data.get("file") or "")
            if file_value.startswith(("http://", "https://")):
                url = file_value
        url = url.strip()
        if not url or url.casefold() in seen:
            continue
        seen.add(url.casefold())
        urls.append(url)
        if len(urls) >= limit:
            break
    return VisionMessagePayload(
        has_image=bool(urls),
        image_urls=tuple(urls),
        plain_text="",
    )
