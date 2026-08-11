"""Bot 内核：按 Provider capabilities 组装多模态消息或文字回退。"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from nonebot import logger

from pallas.core.foundation.logging.bridge import format_business_event
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.providers_store import (
    find_provider,
    load_providers_document,
    provider_allows_native_vision,
    provider_needs_vision_text_fallback,
    resolve_endpoint_for_task,
)
from pallas.product.llm.vision_content import vision_plain_text

_VISION_FETCH_TIMEOUT_SEC = 15.0
_VISION_MAX_BYTES = 8_000_000
_VISION_MAX_IMAGES = 3
_DEFAULT_VISION_PROMPT = "请看看这张图。"
_DESCRIBE_SYSTEM = "你是图片理解助手。用一两句中文描述图片主要内容，不要寒暄。"


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
    try:
        timeout = httpx.Timeout(_VISION_FETCH_TIMEOUT_SEC)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(target)
        if response.status_code != 200:
            logger.warning(format_business_event("视觉图片拉取", "失败", status=response.status_code))
            return None
        data = response.content
        if not data or len(data) > _VISION_MAX_BYTES:
            logger.warning(format_business_event("视觉图片拉取", "已拒绝", bytes=len(data or b"")))
            return None
        mime = str(response.headers.get("content-type") or "image/jpeg").split(";")[0].strip() or "image/jpeg"
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except httpx.HTTPError as exc:
        logger.warning(format_business_event("视觉图片拉取", "失败", error=type(exc).__name__))
        return None


async def fetch_vision_data_uris(metadata: dict[str, Any] | None) -> list[str]:
    images: list[str] = []
    for url in vision_urls_from_metadata(metadata):
        data_uri = await fetch_image_data_uri(url)
        if data_uri:
            images.append(data_uri)
    return images


def openai_vision_user_content(plain: str, data_uris: list[str]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": plain or _DEFAULT_VISION_PROMPT}]
    parts.extend({"type": "image_url", "image_url": {"url": uri}} for uri in data_uris)
    return parts


def replace_last_user_content(messages: list[dict[str, Any]], content: Any) -> list[dict[str, Any]]:
    working = [dict(item) for item in messages]
    for index in range(len(working) - 1, -1, -1):
        if str(working[index].get("role") or "").strip().lower() == "user":
            working[index] = {**working[index], "content": content}
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
        caps = row.get("capabilities") if isinstance(row.get("capabilities"), list) else []
        # 转述只用显式声明了 image 的提供方，避免把遗留空能力再当视觉模型
        if "image" in {str(item or "").strip().lower() for item in caps}:
            return row
    return None


async def describe_images_as_text(
    metadata: dict[str, Any] | None,
    *,
    exclude_provider_id: str = "",
) -> str:
    urls = vision_urls_from_metadata(metadata)
    if not urls:
        return ""
    helper = find_image_capable_provider(exclude_id=exclude_provider_id)
    if helper is None:
        return f"[用户发送了 {len(urls)} 张图片：当前无可用看图模型，已省略图片内容]"

    from pallas.product.llm.provider_client import LlmProviderError, complete_chat_message
    from pallas.product.llm.providers_store import (
        provider_task_model,
        resolve_provider_api_key,
        resolve_provider_base_url,
    )

    data_uris = await fetch_vision_data_uris(metadata)
    if not data_uris:
        return f"[用户发送了 {len(urls)} 张图片：拉取失败，已省略]"

    plain = vision_user_plain_text(metadata)
    content = openai_vision_user_content(f"请简要描述这些图片。用户说：{plain}", data_uris)
    model = provider_task_model(helper, "llm_chat")
    base_url = resolve_provider_base_url(helper)
    if not model or not base_url:
        return f"[用户发送了 {len(urls)} 张图片：看图模型未配置完整]"
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
            api_key=resolve_provider_api_key(helper),
            task="llm_chat",
        )
        text = str(message.get("content") or "").strip()
        if text:
            return f"[图片理解]\n{text}"
    except LlmProviderError as exc:
        logger.warning(
            format_business_event("视觉图片理解", "失败", provider=helper.get("id"), error=type(exc).__name__)
        )
    return f"[用户发送了 {len(urls)} 张图片：理解失败，已省略]"


async def prepare_messages_for_provider_capabilities(
    messages: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None,
    provider_row: dict[str, Any] | None,
    user_text: str = "",
) -> list[dict[str, Any]]:
    """按 capabilities 注入多模态或转成文字描述。"""
    meta = metadata if isinstance(metadata, dict) else {}
    if meta.get("vision_prepared"):
        return messages
    if not metadata_has_vision(metadata):
        return messages

    plain = vision_user_plain_text(metadata, user_text)
    if provider_allows_native_vision(provider_row):
        data_uris = await fetch_vision_data_uris(metadata)
        if data_uris:
            content = openai_vision_user_content(plain, data_uris)
            logger.debug(format_business_event("视觉多模态请求", "已准备", images=len(data_uris), plain_len=len(plain)))
            return replace_last_user_content(messages, content)
        logger.warning(format_business_event("视觉多模态请求", "已降级", reason="no_fetchable_images"))
        return replace_last_user_content(messages, plain or _DEFAULT_VISION_PROMPT)

    if provider_needs_vision_text_fallback(provider_row):
        pid = str((provider_row or {}).get("id") or "")
        described = await describe_images_as_text(metadata, exclude_provider_id=pid)
        merged = plain
        if described:
            merged = f"{plain}\n{described}".strip() if plain else described
        logger.debug(format_business_event("视觉文本回退", "已准备", plain_len=len(plain), desc_len=len(described)))
        return replace_last_user_content(messages, merged or _DEFAULT_VISION_PROMPT)

    return messages


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
        user_text=user_text,
    )
    return prepared, row
