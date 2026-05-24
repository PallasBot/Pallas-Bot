import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.utils.http_msg import PALLAS_VAGUE_REPLY, upstream_error_visible_to_user
from src.plugins.pallas_image.config import ImageApiBackend
from src.plugins.pallas_image.image_api import (
    extract_image_from_generation_payload,
    generations_payload,
    image_api_body_issue_label,
    is_valid_generated_image,
    reply_from_image_api_json,
)
from src.plugins.pallas_image.image_request_options import ImageGenRequestOptions

# 1x1 PNG，用于单测校验
_TEST_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_image_api_body_issue_label_ok_b64() -> None:
    body = f'{{"data":[{{"b64_json":"{_TEST_PNG_B64}"}}]}}'
    assert image_api_body_issue_label(body) is None


def test_image_api_body_issue_label_invalid_image_bytes() -> None:
    assert image_api_body_issue_label('{"data":[{"b64_json":"aGVsbG8="}]}') == "invalid_image"


def test_is_valid_generated_image() -> None:
    import base64

    assert is_valid_generated_image(base64.b64decode(_TEST_PNG_B64))
    assert not is_valid_generated_image(b"hello")
    assert not is_valid_generated_image(b"<html>error</html>" * 8)


def test_extract_image_from_data_url_in_url_field() -> None:
    body = '{"data":[{"url":"data:image/png;base64,aGVsbG8="}]}'
    remote, raw = extract_image_from_generation_payload(json.loads(body))
    assert remote is None
    assert raw == b"hello"


def test_image_api_body_issue_label_upstream_error() -> None:
    body = '{"error":{"message":"quota","type":"new_api_error"}}'
    assert image_api_body_issue_label(body) == "upstream_error"


def test_image_api_body_issue_label_invalid_json() -> None:
    assert image_api_body_issue_label("not-json") == "invalid_json"


def test_image_api_body_issue_label_no_image() -> None:
    assert image_api_body_issue_label('{"data":[]}') == "no_image"


@pytest.mark.asyncio
async def test_reply_rejects_invalid_image_bytes() -> None:
    matcher = MagicMock()
    matcher.finish = AsyncMock()
    matcher.send = AsyncMock()
    body = '{"data":[{"b64_json":"aGVsbG8="}]}'
    ok = await reply_from_image_api_json(
        matcher,
        AsyncMock(),
        body,
        finish_on_error=False,
    )
    assert ok is False
    matcher.send.assert_not_called()
    matcher.finish.assert_not_called()


@pytest.mark.asyncio
async def test_reply_sends_valid_png() -> None:
    matcher = MagicMock()
    matcher.finish = AsyncMock()
    matcher.send = AsyncMock()
    body = f'{{"data":[{{"b64_json":"{_TEST_PNG_B64}"}}]}}'
    ok = await reply_from_image_api_json(
        matcher,
        AsyncMock(),
        body,
        finish_on_error=True,
    )
    assert ok is True
    matcher.send.assert_awaited_once()
    matcher.finish.assert_not_called()


@pytest.mark.asyncio
async def test_reply_finish_on_error_false_on_upstream_error() -> None:
    matcher = MagicMock()
    matcher.finish = AsyncMock()
    matcher.send = AsyncMock()
    body = '{"error":{"message":"quota"}}'
    ok = await reply_from_image_api_json(
        matcher,
        AsyncMock(),
        body,
        finish_on_error=False,
    )
    assert ok is False
    matcher.finish.assert_not_called()
    matcher.send.assert_not_called()


@pytest.mark.asyncio
async def test_reply_finish_on_error_true_on_internal_upstream_error() -> None:
    matcher = MagicMock()
    matcher.finish = AsyncMock()
    body = '{"error":{"message":"预扣费额度失败","code":"insufficient_user_quota"}}'
    ok = await reply_from_image_api_json(
        matcher,
        AsyncMock(),
        body,
        finish_on_error=True,
    )
    assert ok is False
    matcher.finish.assert_awaited_once()
    assert matcher.finish.await_args.args[0] == PALLAS_VAGUE_REPLY


@pytest.mark.asyncio
async def test_reply_finish_on_error_true_on_visible_upstream_error() -> None:
    matcher = MagicMock()
    matcher.finish = AsyncMock()
    body = '{"error":{"message":"内容违规，请修改提示词","code":"content_policy_violation"}}'
    ok = await reply_from_image_api_json(
        matcher,
        AsyncMock(),
        body,
        finish_on_error=True,
    )
    assert ok is False
    matcher.finish.assert_awaited_once()
    assert matcher.finish.await_args.args[0] == "内容违规，请修改提示词"
    assert upstream_error_visible_to_user(body)


def test_generations_payload_uses_options() -> None:
    opts = ImageGenRequestOptions(
        size="512x512",
        quality="high",
        response_format="url",
        include_ref_images=False,
    )
    backend = ImageApiBackend(
        base_url="https://api.example.com/",
        api_key="sk-test",
        model="m",
        label="primary",
    )
    payload = generations_payload("p", ["http://x/a.png"], model="m", backend=backend, options=opts)
    assert payload["size"] == "512x512"
    assert payload["quality"] == "high"
    assert payload["response_format"] == "url"
    assert "image" not in payload


def test_generations_payload_omits_response_format_when_configured() -> None:
    backend = ImageApiBackend(
        base_url="https://gateway.example.net/api/",
        api_key="sk-test",
        model="m",
        label="fallback-0",
        omit_response_format=True,
    )
    opts = ImageGenRequestOptions(response_format="b64_json")
    payload = generations_payload("p", [], model="m", backend=backend, options=opts)
    assert "response_format" not in payload
