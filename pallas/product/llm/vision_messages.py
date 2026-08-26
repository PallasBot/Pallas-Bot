"""Bot 内核：按 Provider capabilities 组装多模态消息或文字回退。"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import httpx
from nonebot import logger

from pallas.core.foundation.logging.bridge import format_business_event
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.providers_store import (
    find_provider,
    load_providers_document,
    provider_allows_native_vision,
    resolve_endpoint_for_task,
)
from pallas.product.llm.vision_content import (
    _VISION_HISTORY_PLACEHOLDER,
    extract_vision_message_payload,
    vision_plain_text,
)

_VISION_FETCH_TIMEOUT_SEC = 15.0
_VISION_MAX_BYTES = 8_000_000
_VISION_MAX_IMAGES = 3
_DEFAULT_VISION_PROMPT = "请看看这张图。"
_VISION_FETCH_FAILED_NOTICE = "（用户发送了图片，但图片加载失败，无法查看。请如实告知用户你暂时看不到这张图。）"
_DESCRIBE_SYSTEM = "你是图片理解助手。用一两句中文描述图片主要内容，不要寒暄。"


def image_bytes_to_data_uri(data: bytes) -> str | None:
    """用 Pillow 探测二进制图片的真实 MIME，转成 data URI；非图片返回 None。"""
    if not data or len(data) > _VISION_MAX_BYTES:
        return None
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(BytesIO(data)) as image:
            fmt = str(image.format or "").lower()
    except (OSError, UnidentifiedImageError):
        return None
    mime = {
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(fmt)
    if not mime:
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def metadata_has_vision(metadata: dict[str, Any] | None) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    if meta.get("has_image"):
        return True
    urls = meta.get("vision_image_urls")
    return isinstance(urls, list) and bool(urls)


def vision_urls_from_metadata(metadata: dict[str, Any] | None) -> list[str]:
    meta = metadata if isinstance(metadata, dict) else {}
    raw = meta.get("vision_image_urls")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw[:_VISION_MAX_IMAGES]:
        url = str(item or "").strip()
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


def group_timeline_images_from_metadata(metadata: dict[str, Any] | None) -> list[dict[str, str]]:
    meta = metadata if isinstance(metadata, dict) else {}
    raw = meta.get("group_timeline_images")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "speaker": str(item.get("speaker") or "群友").strip() or "群友",
            "text": str(item.get("text") or "").strip(),
            "url": url,
        })
        if len(out) >= _VISION_MAX_IMAGES:
            break
    return out


def vision_user_plain_text(metadata: dict[str, Any] | None, user_text: str = "") -> str:
    meta = metadata if isinstance(metadata, dict) else {}
    plain = str(meta.get("vision_plain_text") or "").strip()
    if plain:
        return plain
    plain = vision_plain_text(user_text)
    return plain or _DEFAULT_VISION_PROMPT


async def fetch_image_data_uri(url: str) -> str | None:
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        return None
    if target.startswith("data:"):
        return target
    # QQ 多媒体 URL 常带签名且会过期，裸 GET 每次都先打一次外网拿 400 才回退。
    # 先查本地缓存：命中就直接复用，避免每次带图都先失败一次并刷 status=400 日志。
    cached_uri = await _fetch_cached_image_data_uri(target)
    if cached_uri:
        return cached_uri
    data_uri: str | None = None
    try:
        timeout = httpx.Timeout(_VISION_FETCH_TIMEOUT_SEC)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(target)
        if response.status_code == 200:
            data = response.content
            if data and len(data) <= _VISION_MAX_BYTES:
                mime = str(response.headers.get("content-type") or "image/jpeg").split(";")[0].strip() or "image/jpeg"
                if not mime.startswith("image/"):
                    mime = "image/jpeg"
                encoded = base64.b64encode(data).decode("ascii")
                data_uri = f"data:{mime};base64,{encoded}"
        else:
            logger.warning(format_business_event("视觉图片拉取", "失败", status=response.status_code))
    except httpx.HTTPError as exc:
        logger.warning(format_business_event("视觉图片拉取", "失败", error=type(exc).__name__))
    if data_uri:
        return data_uri
    return await _fetch_cached_image_data_uri(target)


async def _fetch_cached_image_data_uri(url: str) -> str | None:
    """裸 GET 失败时回退到图片缓存，避免 QQ URL 过期导致图被丢。"""
    from pallas.core.shared.utils import media_cache

    try:
        cached = await media_cache.get_image_by_url(url)
    except Exception as exc:
        logger.warning(format_business_event("视觉图片拉取", "缓存回退失败", error=type(exc).__name__))
        return None
    if not cached:
        return None
    data_uri = image_bytes_to_data_uri(cached)
    if data_uri:
        logger.info(format_business_event("视觉图片拉取", "缓存命中", bytes=len(cached)))
    else:
        logger.warning(format_business_event("视觉图片拉取", "缓存内容非法", bytes=len(cached)))
    return data_uri


async def fetch_vision_data_uris(metadata: dict[str, Any] | None) -> list[str]:
    images: list[str] = []
    for url in vision_urls_from_metadata(metadata):
        try:
            data_uri = await fetch_image_data_uri(url)
        except Exception as exc:
            logger.warning(format_business_event("视觉图片拉取", "失败", error=type(exc).__name__))
            continue
        if data_uri:
            images.append(data_uri)
    return images


async def fetch_group_timeline_data_uris(
    metadata: dict[str, Any] | None,
) -> list[tuple[dict[str, str], str]]:
    fetched: list[tuple[dict[str, str], str]] = []
    for item in group_timeline_images_from_metadata(metadata):
        try:
            data_uri = await fetch_image_data_uri(item["url"])
        except Exception as exc:
            logger.warning(format_business_event("群聊历史图片拉取", "失败", error=type(exc).__name__))
            continue
        if data_uri:
            fetched.append((item, data_uri))
    return fetched


def openai_vision_user_content(plain: str, data_uris: list[str]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": plain or _DEFAULT_VISION_PROMPT}]
    parts.extend({"type": "image_url", "image_url": {"url": uri}} for uri in data_uris)
    return parts


def openai_group_timeline_user_content(
    fetched: list[tuple[dict[str, str], str]],
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": "【刚才群聊中的图片】"}]
    for item, data_uri in fetched:
        text = item["text"] or "[图片]"
        parts.extend([
            {"type": "text", "text": f"{item['speaker']}：{text}"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ])
    return parts


def replace_last_user_content(messages: list[dict[str, Any]], content: Any) -> list[dict[str, Any]]:
    working = [dict(item) for item in messages]
    for index in range(len(working) - 1, -1, -1):
        if str(working[index].get("role") or "").strip().lower() == "user":
            working[index] = {**working[index], "content": content}
            return working
    working.append({"role": "user", "content": content})
    return working


def insert_before_last_user_content(messages: list[dict[str, Any]], content: Any) -> list[dict[str, Any]]:
    working = [dict(item) for item in messages]
    for index in range(len(working) - 1, -1, -1):
        if str(working[index].get("role") or "").strip().lower() == "user":
            working.insert(index, {"role": "user", "content": content})
            return working
    working.append({"role": "user", "content": content})
    return working


def find_image_capable_provider(*, exclude_id: str = "") -> dict[str, Any] | None:
    doc = load_providers_document()
    skip = str(exclude_id or "").strip()
    for row in doc.get("providers") or []:
        if not isinstance(row, dict):
            continue
        if row.get("enabled", True) is False:
            continue
        pid = str(row.get("id") or "").strip()
        if not pid or pid == skip:
            continue
        from pallas.product.llm.providers_store import provider_capabilities, provider_task_model

        caps = provider_capabilities(row, provider_task_model(row, "llm_chat"))
        # 转述只用显式声明了 image 的提供方，避免把遗留空能力再当视觉模型
        if "image" in {str(item or "").strip().lower() for item in caps}:
            return row
    return None


async def _run_vision_description(
    content: list[dict[str, Any]],
    *,
    urls_count: int,
    provider_id: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    request_method: str | None = None,
) -> str:
    from pallas.product.llm.provider_client import LlmProviderError, complete_chat_message

    if not model or not base_url:
        return f"[用户发送了 {urls_count} 张图片：看图模型未配置完整]"
    try:
        message = await complete_chat_message(
            [
                {"role": "system", "content": _DESCRIBE_SYSTEM},
                {"role": "user", "content": content},
            ],
            model=model,
            options={"num_predict": task_token_budget("vision_messages"), "temperature": 0.2},
            tools=None,
            base_url=base_url,
            api_key=api_key,
            request_method=request_method,
            task="llm_chat",
            provider_id=provider_id,
        )
        text = str(message.get("content") or "").strip()
        if text:
            return f"[图片理解]\n{text}"
    except LlmProviderError as exc:
        logger.warning(format_business_event("视觉图片理解", "失败", provider=provider_id, error=type(exc).__name__))
    return f"[用户发送了 {urls_count} 张图片：理解失败，已省略]"


async def describe_images_as_text(
    metadata: dict[str, Any] | None,
    *,
    exclude_provider_id: str = "",
) -> str:
    urls = vision_urls_from_metadata(metadata)
    if not urls:
        return ""

    data_uris = await fetch_vision_data_uris(metadata)
    if not data_uris:
        return f"[用户发送了 {len(urls)} 张图片：拉取失败，已省略]"

    plain = vision_user_plain_text(metadata)
    content = openai_vision_user_content(f"请简要描述这些图片。用户说：{plain}", data_uris)

    # 优先复用用户配置的视觉模型（sticker_vision 任务端点），无则回退自动探测
    endpoint = resolve_endpoint_for_task("sticker_vision")
    if endpoint is not None and "image" in endpoint.capabilities:
        return await _run_vision_description(
            content,
            urls_count=len(urls),
            provider_id=str(endpoint.provider_id or ""),
            model=endpoint.model,
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            request_method=getattr(endpoint, "request_method", None),
        )

    from pallas.product.llm.providers_store import (
        provider_task_model,
        resolve_provider_api_key,
        resolve_provider_base_url,
    )

    helper = find_image_capable_provider(exclude_id=exclude_provider_id)
    if helper is None:
        return f"[用户发送了 {len(urls)} 张图片：当前无可用看图模型，已省略图片内容]"
    return await _run_vision_description(
        content,
        urls_count=len(urls),
        provider_id=str(helper.get("id") or ""),
        model=provider_task_model(helper, "llm_chat"),
        base_url=resolve_provider_base_url(helper),
        api_key=resolve_provider_api_key(helper),
    )


async def describe_vision_content_for_history(text: str) -> str:
    """把会话历史消息里的 [CQ:image] 用视觉模型描述后以文本形式保留，供摘要识图。

    无图或无可用看图模型时原样返回（保持既有剥离为 [图片] 的行为）。耗时调用在
    `llm_session_vision_describe_enabled` 开启时才会发生；任何失败都回退为不描述。
    """
    raw = str(text or "")
    payload = extract_vision_message_payload(raw)
    if not payload.image_urls:
        return raw
    metadata: dict[str, Any] = {
        "vision_image_urls": list(payload.image_urls),
        "vision_plain_text": payload.plain_text,
        "has_image": True,
    }
    try:
        described = await describe_images_as_text(metadata)
    except Exception as exc:
        logger.warning(format_business_event("历史图片描述", "已跳过", error=type(exc).__name__))
        return raw
    if not described:
        return raw
    stripped = vision_plain_text(raw)
    if stripped:
        return f"{_VISION_HISTORY_PLACEHOLDER}({described}) {stripped}".strip()
    return f"{_VISION_HISTORY_PLACEHOLDER}({described})"


async def prepare_messages_for_provider_capabilities(
    messages: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None,
    provider_row: dict[str, Any] | None,
    model: str = "",
    user_text: str = "",
) -> list[dict[str, Any]]:
    """按 capabilities 注入多模态或转成文字描述。"""
    meta = metadata if isinstance(metadata, dict) else {}
    if meta.get("vision_prepared"):
        return messages
    current_has_vision = metadata_has_vision(metadata)
    timeline_images = group_timeline_images_from_metadata(metadata)
    if not current_has_vision and not timeline_images:
        return messages

    native_vision = provider_allows_native_vision(provider_row, model)
    if native_vision:
        working = messages
        if current_has_vision:
            plain = vision_user_plain_text(metadata, user_text)
            data_uris = await fetch_vision_data_uris(metadata)
            if data_uris:
                content = openai_vision_user_content(plain, data_uris)
                logger.debug(
                    format_business_event("视觉多模态请求", "已准备", images=len(data_uris), plain_len=len(plain))
                )
                working = replace_last_user_content(working, content)
                fetched_history = await fetch_group_timeline_data_uris(metadata)
                if fetched_history:
                    working = insert_before_last_user_content(
                        working,
                        openai_group_timeline_user_content(fetched_history),
                    )
            else:
                logger.warning(format_business_event("视觉多模态请求", "已降级", reason="no_fetchable_images"))
                degraded = f"{plain or _DEFAULT_VISION_PROMPT}\n{_VISION_FETCH_FAILED_NOTICE}".strip()
                working = replace_last_user_content(working, degraded)
        return working

    if not current_has_vision:
        return messages

    plain = vision_user_plain_text(metadata, user_text)
    pid = str((provider_row or {}).get("id") or "")
    described = await describe_images_as_text(metadata, exclude_provider_id=pid)
    merged = plain
    if described:
        merged = f"{plain}\n{described}".strip() if plain else described
    logger.debug(format_business_event("视觉文本回退", "已准备", plain_len=len(plain), desc_len=len(described)))
    return replace_last_user_content(messages, merged or _DEFAULT_VISION_PROMPT)


async def prepare_kernel_chat_messages(
    messages: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None,
    task: str = "llm_chat",
    user_text: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    endpoint = resolve_endpoint_for_task(task)
    row = find_provider(endpoint.provider_id) if endpoint is not None else None
    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata=metadata,
        provider_row=row,
        model=endpoint.model if endpoint is not None else "",
        user_text=user_text,
    )
    return prepared, row
