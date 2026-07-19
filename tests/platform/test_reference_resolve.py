from __future__ import annotations

import base64

import httpx
import pytest

from pallas.core.platform.media.reference_resolve import (
    ReferenceDownloadOptions,
    bytes_to_data_reference_url,
    decode_inline_image_reference,
    reference_request_headers,
    reference_token_to_bytes,
    resolve_reference_inline_urls,
)

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADU0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_reference_request_headers_adds_referer_for_qq_cdn() -> None:
    options = ReferenceDownloadOptions(user_agent="curl/8.5.0")
    headers = reference_request_headers("https://gchat.qpic.cn/download/abc", options)
    assert headers["Referer"] == "https://qun.qq.com/"
    assert headers["User-Agent"]


def test_reference_token_to_bytes_supports_data_and_base64_urls() -> None:
    data_url = bytes_to_data_reference_url(PNG_BYTES)
    assert reference_token_to_bytes(data_url) == PNG_BYTES
    b64_url = f"base64://{base64.b64encode(PNG_BYTES).decode('ascii')}"
    assert reference_token_to_bytes(b64_url) == PNG_BYTES


@pytest.mark.asyncio
async def test_resolve_reference_inline_urls_downloads_http(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_download(client, url, *, options, download_timeout: float) -> bytes | None:
        assert url == "https://gchat.qpic.cn/download/abc"
        assert download_timeout == 30.0
        return PNG_BYTES

    monkeypatch.setattr(
        "pallas.core.platform.media.reference_resolve.download_reference_bytes_with_transport",
        fake_download,
    )

    async with httpx.AsyncClient() as client:
        result = await resolve_reference_inline_urls(
            client,
            ["https://gchat.qpic.cn/download/abc"],
            options=ReferenceDownloadOptions(),
            download_timeout=30.0,
        )

    assert len(result.inline_urls) == 1
    assert not result.failed_tokens
    assert decode_inline_image_reference(result.inline_urls[0]) == PNG_BYTES
