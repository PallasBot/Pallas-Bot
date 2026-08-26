from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from pallas.product.llm.providers_store import (
    clear_providers_store_cache,
    provider_allows_native_vision,
    provider_needs_vision_text_fallback,
    save_providers_document,
)
from pallas.product.llm.vision_messages import (
    openai_vision_user_content,
    prepare_messages_for_provider_capabilities,
    replace_last_user_content,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_provider_vision_capability_helpers() -> None:
    assert provider_allows_native_vision({"capabilities": ["text", "image"]}) is True
    assert provider_allows_native_vision({"capabilities": ["text"]}) is False
    assert provider_allows_native_vision({"capabilities": []}) is False
    assert provider_allows_native_vision(None) is False
    assert provider_needs_vision_text_fallback({"capabilities": ["text"]}) is True


def test_openai_vision_user_content_shape() -> None:
    parts = openai_vision_user_content("看看", ["data:image/jpeg;base64,aaa"])
    assert parts[0] == {"type": "text", "text": "看看"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:")


def test_prepare_messages_native_vision(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()

    async def fake_fetch(_metadata):
        return ["data:image/jpeg;base64,ZmFrZQ=="]

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_vision_data_uris", fake_fetch)

    messages = [{"role": "user", "content": "old"}]
    meta = {
        "has_image": True,
        "vision_image_urls": ["https://example.com/a.png"],
        "vision_plain_text": "这是什么",
    }
    row = {"id": "vision", "capabilities": ["text", "image"]}

    prepared = asyncio.run(
        prepare_messages_for_provider_capabilities(
            messages,
            metadata=meta,
            provider_row=row,
            user_text="看图",
        )
    )
    content = prepared[-1]["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "这是什么"
    assert content[1]["type"] == "image_url"


def test_prepare_messages_text_fallback_without_helper(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "text-only",
                "kind": "remote",
                "base_url": "https://example.com/v1",
                "api_key": "sk-x",
                "default_model": "m1",
                "capabilities": ["text"],
            }
        ],
        "routing": {"tasks": {"llm_chat": "text-only"}},
    })

    messages = [{"role": "user", "content": "old"}]
    meta = {
        "has_image": True,
        "vision_image_urls": ["https://example.com/a.png"],
        "vision_plain_text": "看看",
    }
    row = {"id": "text-only", "capabilities": ["text"]}
    prepared = asyncio.run(
        prepare_messages_for_provider_capabilities(
            messages,
            metadata=meta,
            provider_row=row,
            user_text="看图",
        )
    )
    content = str(prepared[-1]["content"])
    assert "看看" in content
    assert "图片" in content


def test_replace_last_user_content() -> None:
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    out = replace_last_user_content(messages, "new")
    assert out[-1]["content"] == "new"
    assert out[0]["content"] == "s"


@pytest.mark.asyncio
async def test_prepare_messages_native_vision_plain_text_ignores_group_timeline_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(url: str) -> str | None:
        return {
            "https://example.com/history.png": "data:image/png;base64,aGk=",
        }.get(url)

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "上一句"},
        {"role": "user", "content": "现在呢"},
    ]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "group_timeline_images": [
                {"speaker": "兔兔", "text": "看这个", "url": "https://example.com/history.png"},
            ]
        },
        provider_row={"id": "vision", "capabilities": ["text", "image"]},
        model="vision-model",
    )

    assert prepared == messages


@pytest.mark.asyncio
async def test_prepare_messages_native_vision_with_current_image_injects_group_timeline_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(url: str) -> str | None:
        return {
            "https://example.com/current.png": "data:image/png;base64,Y3VycmVudA==",
            "https://example.com/history.png": "data:image/png;base64,aGk=",
        }.get(url)

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "上一句"},
        {"role": "user", "content": "原始消息"},
    ]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "has_image": True,
            "vision_image_urls": ["https://example.com/current.png"],
            "vision_plain_text": "现在呢",
            "group_timeline_images": [
                {"speaker": "兔兔", "text": "看这个", "url": "https://example.com/history.png"},
            ],
        },
        provider_row={"id": "vision", "capabilities": ["text", "image"]},
        model="vision-model",
    )

    assert [item["role"] for item in prepared] == ["system", "assistant", "user", "user"]
    history_content = prepared[-2]["content"]
    assert history_content[0] == {"type": "text", "text": "【刚才群聊中的图片】"}
    assert history_content[1] == {"type": "text", "text": "兔兔：看这个"}
    assert history_content[2] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGk="},
    }
    last = prepared[-1]["content"]
    assert any(item.get("type") == "image_url" for item in last)


@pytest.mark.asyncio
async def test_prepare_messages_native_vision_recognition_ask_skips_group_timeline_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(url: str) -> str | None:
        return {
            "https://example.com/current.png": "data:image/png;base64,Y3VycmVudA==",
            "https://example.com/history.png": "data:image/png;base64,aGk=",
        }.get(url)

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "上一句"},
        {"role": "user", "content": "原始消息"},
    ]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "has_image": True,
            "vision_image_urls": ["https://example.com/current.png"],
            "vision_plain_text": "这是谁呀",
            "group_timeline_images": [
                {"speaker": "兔兔", "text": "看这个", "url": "https://example.com/history.png"},
            ],
        },
        provider_row={"id": "vision", "capabilities": ["text", "image"]},
        model="vision-model",
        user_text="这是谁呀",
    )

    assert [item["role"] for item in prepared] == ["system", "assistant", "user"]
    last = prepared[-1]["content"]
    assert any(item.get("type") == "image_url" for item in last)
    assert not any(
        part.get("type") == "text" and "刚才群聊中的图片" in str(part.get("text") or "")
        for parts in (item.get("content") for item in prepared if isinstance(item.get("content"), list))
        for part in parts
    )


@pytest.mark.asyncio
async def test_prepare_messages_text_provider_ignores_group_timeline_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(_url: str) -> str | None:
        return None

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [{"role": "user", "content": "现在呢"}]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "group_timeline_images": [
                {"speaker": "兔兔", "text": "看这个", "url": "https://example.com/history.png"},
            ]
        },
        provider_row={"id": "text", "capabilities": ["text"]},
        model="text-model",
    )

    assert prepared == messages


@pytest.mark.asyncio
async def test_prepare_messages_history_image_download_failure_keeps_original_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(_url: str) -> None:
        return None

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [{"role": "user", "content": "现在呢"}]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "group_timeline_images": [
                {"speaker": "兔兔", "text": "看这个", "url": "https://example.com/history.png"},
            ]
        },
        provider_row={"id": "vision", "capabilities": ["text", "image"]},
        model="vision-model",
    )

    assert prepared == messages


@pytest.mark.asyncio
async def test_prepare_messages_history_image_download_exception_keeps_original_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(_url: str) -> str | None:
        raise ValueError("invalid image URL")

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [{"role": "user", "content": "现在呢"}]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "group_timeline_images": [
                {"speaker": "兔兔", "text": "看这个", "url": "https://example.com/history.png"},
            ]
        },
        provider_row={"id": "vision", "capabilities": ["text", "image"]},
        model="vision-model",
    )

    assert prepared == messages


def test_image_bytes_to_data_uri_sniffs_mime_and_ignores_over_size() -> None:
    from pallas.product.llm.vision_messages import image_bytes_to_data_uri

    gif = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
        b"\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
    )
    uri = image_bytes_to_data_uri(gif)
    assert uri is not None
    assert uri.startswith("data:image/gif;base64,")
    assert image_bytes_to_data_uri(b"not an image") is None


@pytest.mark.asyncio
async def test_fetch_image_data_uri_falls_back_to_media_cache_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from pallas.core.shared.utils import media_cache as mcache
    from pallas.product.llm import vision_messages as vm

    gif = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
        b"\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
    )

    async def fake_get_image(_url: str) -> bytes | None:
        return gif

    monkeypatch.setattr(mcache, "get_image_by_url", fake_get_image)

    class FailingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url: str):
            raise httpx.ConnectError("network down")

    monkeypatch.setattr("pallas.product.llm.vision_messages.httpx.AsyncClient", FailingClient)

    uri = await vm.fetch_image_data_uri("https://example.com/expired.gif")
    assert uri is not None
    assert uri.startswith("data:image/gif;base64,")


@pytest.mark.asyncio
async def test_fetch_image_data_uri_prefers_media_cache_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from pallas.core.shared.utils import media_cache as mcache
    from pallas.product.llm import vision_messages as vm

    gif = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
        b"\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
    )

    async def fake_get_image(_url: str) -> bytes | None:
        return gif

    monkeypatch.setattr(mcache, "get_image_by_url", fake_get_image)
    called = {"bare_get": False}

    class FailingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url: str):
            called["bare_get"] = True
            raise httpx.ConnectError("should not reach network")

    monkeypatch.setattr("pallas.product.llm.vision_messages.httpx.AsyncClient", FailingClient)

    uri = await vm.fetch_image_data_uri("https://example.com/cached-by-url.gif")
    assert uri is not None
    assert uri.startswith("data:image/gif;base64,")
    assert called["bare_get"] is False


@pytest.mark.asyncio
async def test_prepare_messages_current_image_download_exception_degrades_to_failed_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(_url: str) -> str | None:
        raise ValueError("invalid image URL")

    monkeypatch.setattr("pallas.product.llm.vision_messages.fetch_image_data_uri", fake_fetch)
    messages = [{"role": "user", "content": "原始消息"}]

    prepared = await prepare_messages_for_provider_capabilities(
        messages,
        metadata={
            "has_image": True,
            "vision_image_urls": ["https://example.com/current.png"],
            "vision_plain_text": "看看这张",
        },
        provider_row={"id": "vision", "capabilities": ["text", "image"]},
        model="vision-model",
    )

    verbose = str(prepared[-1]["content"])
    assert verbose.startswith("看看这张")
    assert "图片加载失败" in verbose


@pytest.mark.asyncio
async def test_describe_vision_content_for_history_injects_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.vision_messages import describe_vision_content_for_history

    async def fake_describe(_metadata: dict) -> str:
        return "[图片理解]\n一头萨摩耶犬"

    monkeypatch.setattr("pallas.product.llm.vision_messages.describe_images_as_text", fake_describe)

    raw = "[CQ:image,file=a.jpg,url=https://example.com/a.png] 这是谁"
    out = await describe_vision_content_for_history(raw)
    assert "萨摩耶" in out
    assert "这是谁" in out
    assert "CQ:image" not in out


@pytest.mark.asyncio
async def test_describe_vision_content_for_history_no_urls_is_unchanged() -> None:
    from pallas.product.llm.vision_messages import describe_vision_content_for_history

    raw = "纯文本，没有图"
    out = await describe_vision_content_for_history(raw)
    assert out == raw


@pytest.mark.asyncio
async def test_describe_vision_content_for_history_describe_failure_keeps_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.vision_messages import describe_vision_content_for_history

    async def fake_describe(_metadata: dict) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr("pallas.product.llm.vision_messages.describe_images_as_text", fake_describe)

    raw = "[CQ:image,file=a.jpg,url=https://example.com/a.png] 这是谁"
    out = await describe_vision_content_for_history(raw)
    assert out == raw
