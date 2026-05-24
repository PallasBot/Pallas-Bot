import asyncio
import base64
import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import httpx
from curl_cffi import CurlMime
from curl_cffi.requests import AsyncSession as CffiAsyncSession
from curl_cffi.requests import RequestsError as CffiRequestsError
from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from src.common.utils.http_msg import PALLAS_VAGUE_REPLY, user_failure_reply

from .config import ImageApiBackend, image_gen_config
from .image_request_options import ImageGenRequestOptions


def schedule_persist_generated_draw(data: bytes, group_id: int, user_id: int) -> None:
    """后台归档，避免阻塞发图。"""

    async def job() -> None:
        try:
            from .draw_archive import persist_generated_draw

            await persist_generated_draw(data, group_id, user_id)
        except Exception as e:
            logger.warning(f"pallas_image persist archive failed group={group_id}: {e}")

    asyncio.create_task(job(), name=f"pallas_draw_archive:{group_id}:{user_id}")


def image_api_base(backend: ImageApiBackend) -> str:
    base = (backend.base_url or "").strip()
    if not base:
        return ""
    return base if base.endswith("/") else base + "/"


def image_gen_endpoint(backend: ImageApiBackend) -> str:
    b = image_api_base(backend)
    return urljoin(b, "v1/images/generations") if b else ""


def image_edits_endpoint(backend: ImageApiBackend) -> str:
    b = image_api_base(backend)
    return urljoin(b, "v1/images/edits") if b else ""


def image_gen_optional_headers() -> dict[str, str]:
    ua = (image_gen_config.http_user_agent or "").strip()
    return {"User-Agent": ua} if ua else {}


def effective_http_transport() -> str:
    raw = (image_gen_config.http_transport or "auto").strip().lower()
    if raw in ("", "auto"):
        return "auto"
    if raw in ("httpx", "curl", "cffi"):
        return raw
    logger.warning("unknown image http_transport {}, fallback to auto", raw)
    return "auto"


def effective_request_timeout(override: float | None = None) -> float:
    """单次 POST 超时；override 通常为画画总超时剩余秒数。"""
    base = image_gen_config.request_timeout
    if override is None:
        return base
    return max(1.0, min(base, override))


def request_timeout_for_deadline(remaining_seconds: float) -> float:
    return effective_request_timeout(remaining_seconds)


def cffi_error_is_timeout(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "(28)" in msg or "timed out" in msg or "timeout" in msg


def httpx_cap_after_cffi_timeout(req_timeout_cap: float | None) -> float | None:
    """cffi 读超时后若预算仍够，给 httpx 一段独立时间再试（优先出图）。"""
    budget = effective_request_timeout(req_timeout_cap)
    if budget < 50:
        return None
    fallback = max(45.0, min(image_gen_config.request_timeout, budget * 0.55))
    return fallback if fallback >= 45 else None


async def try_httpx_after_cffi_timeout(
    exc: BaseException,
    req_timeout_cap: float | None,
    httpx_call,
) -> tuple[int, str] | None:
    if not cffi_error_is_timeout(exc):
        return None
    cap = httpx_cap_after_cffi_timeout(req_timeout_cap)
    if cap is None:
        return None
    logger.info(f"pallas_image cffi read timeout, retry httpx cap={cap:.0f}s (prioritize image)")
    return await httpx_call(cap)


def image_gen_auth_headers_json(backend: ImageApiBackend) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {backend.api_key}",
        "Content-Type": "application/json",
    }
    h.update(image_gen_optional_headers())
    return h


def image_gen_auth_headers_multipart(backend: ImageApiBackend) -> dict[str, str]:
    h = {"Authorization": f"Bearer {backend.api_key}"}
    h.update(image_gen_optional_headers())
    return h


async def httpx_post_generations(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    *,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    req_timeout = effective_request_timeout(req_timeout_cap)
    r = await client.post(
        url,
        headers=headers,
        json=payload,
        timeout=httpx.Timeout(req_timeout, connect=min(30.0, req_timeout)),
    )
    return r.status_code, r.text


async def curl_cffi_post_generations(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    *,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    cfg = image_gen_config
    impersonate = (cfg.tls_impersonate or "").strip()
    if not impersonate:
        raise ValueError("tls_impersonate 为空")
    req_timeout = effective_request_timeout(req_timeout_cap)
    async with CffiAsyncSession() as session:
        r = await session.post(
            url,
            headers=headers,
            json=payload,
            impersonate=impersonate,
            timeout=req_timeout,
        )
        return r.status_code, r.text


async def curl_post_generations(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    *,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    if not shutil.which("curl"):
        raise RuntimeError("未找到 curl 可执行文件，请安装 curl 或将 pallas_image_http_transport 设为 httpx")
    timeout_s = int(max(10, min(effective_request_timeout(req_timeout_cap), 600)))
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as tf:
        json.dump(payload, tf, ensure_ascii=False)
        body_path = tf.name
    try:
        args: list[str] = [
            "curl",
            "-sS",
            "-m",
            str(timeout_s),
            "--connect-timeout",
            "30",
            "-X",
            "POST",
            url,
            "-w",
            "\n%{http_code}",
        ]
        for k, v in headers.items():
            args.extend(["-H", f"{k}: {v}"])
        args.extend(["--data-binary", f"@{body_path}"])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"curl 退出码 {proc.returncode}: {err}")
        raw = stdout.decode("utf-8", errors="replace")
        if "\n" not in raw:
            return 0, raw
        body, code_line = raw.rsplit("\n", 1)
        try:
            return int(code_line.strip()), body
        except ValueError:
            return 0, raw
    finally:

        def unlink_body() -> None:
            Path(body_path).unlink(missing_ok=True)

        try:
            await asyncio.to_thread(unlink_body)
        except OSError:
            pass


async def post_generations_with_transport(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    *,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    mode = effective_http_transport()
    cfg = image_gen_config
    if mode == "curl":
        return await curl_post_generations(url, headers, payload, req_timeout_cap=req_timeout_cap)
    if mode == "httpx":
        return await httpx_post_generations(client, url, headers, payload, req_timeout_cap=req_timeout_cap)
    if mode == "cffi":
        return await curl_cffi_post_generations(url, headers, payload, req_timeout_cap=req_timeout_cap)
    tcap = req_timeout_cap
    if (cfg.tls_impersonate or "").strip():
        try:
            return await curl_cffi_post_generations(url, headers, payload, req_timeout_cap=tcap)
        except (CffiRequestsError, OSError, ValueError) as e:
            ret = await try_httpx_after_cffi_timeout(
                e,
                tcap,
                lambda cap: httpx_post_generations(client, url, headers, payload, req_timeout_cap=cap),
            )
            if ret is not None:
                return ret
            if cffi_error_is_timeout(e):
                raise
            logger.warning(f"pallas_image generations curl_cffi failed, fallback httpx: {e}")
    try:
        return await httpx_post_generations(client, url, headers, payload, req_timeout_cap=tcap)
    except httpx.ConnectError as e:
        logger.warning(f"pallas_image generations httpx connect failed, fallback curl: {e}")
        return await curl_post_generations(url, headers, payload, req_timeout_cap=req_timeout_cap)


def should_send_response_format(backend: ImageApiBackend, opts: ImageGenRequestOptions) -> bool:
    if backend.omit_response_format:
        return False
    return bool(opts.response_format)


def edit_request_fields(
    prompt: str,
    backend: ImageApiBackend,
    *,
    options: ImageGenRequestOptions | None = None,
) -> dict[str, str]:
    opts = options or ImageGenRequestOptions.from_config()
    data: dict[str, str] = {"prompt": prompt, "model": backend.model}
    if opts.size:
        data["size"] = opts.size
    elif opts.aspect_ratio:
        data["aspect_ratio"] = opts.aspect_ratio
    if opts.quality:
        data["quality"] = opts.quality
    if should_send_response_format(backend, opts):
        data["response_format"] = opts.response_format
    return data


async def httpx_post_edits(
    client: httpx.AsyncClient,
    image_blobs: list[bytes],
    prompt: str,
    backend: ImageApiBackend,
    *,
    options: ImageGenRequestOptions | None = None,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    endpoint = image_edits_endpoint(backend)
    headers = image_gen_auth_headers_multipart(backend)
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for i, blob in enumerate(image_blobs):
        files.append(("image", (f"ref_{i}.png", blob, "image/png")))
    data = edit_request_fields(prompt, backend, options=options)
    req_timeout = effective_request_timeout(req_timeout_cap)
    r = await client.post(
        endpoint,
        headers=headers,
        files=files,
        data=data,
        timeout=httpx.Timeout(req_timeout, connect=min(30.0, req_timeout)),
    )
    return r.status_code, r.text


async def curl_cffi_post_edits(
    image_blobs: list[bytes],
    prompt: str,
    backend: ImageApiBackend,
    *,
    options: ImageGenRequestOptions | None = None,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    cfg = image_gen_config
    impersonate = (cfg.tls_impersonate or "").strip()
    if not impersonate:
        raise ValueError("tls_impersonate 为空")
    endpoint = image_edits_endpoint(backend)
    headers = image_gen_auth_headers_multipart(backend)
    mp = CurlMime()
    for i, blob in enumerate(image_blobs):
        mp.addpart("image", data=blob, filename=f"ref_{i}.png", content_type="image/png")
    data = edit_request_fields(prompt, backend, options=options)
    req_timeout = effective_request_timeout(req_timeout_cap)
    async with CffiAsyncSession() as session:
        r = await session.post(
            endpoint,
            headers=headers,
            multipart=mp,
            data=data,
            impersonate=impersonate,
            timeout=req_timeout,
        )
        return r.status_code, r.text


async def curl_post_edits(
    image_blobs: list[bytes],
    prompt: str,
    backend: ImageApiBackend,
    *,
    options: ImageGenRequestOptions | None = None,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    if not shutil.which("curl"):
        raise RuntimeError("未找到 curl 可执行文件")
    endpoint = image_edits_endpoint(backend)
    headers = image_gen_auth_headers_multipart(backend)
    timeout_s = int(max(10, min(effective_request_timeout(req_timeout_cap), 600)))
    with tempfile.TemporaryDirectory() as td:
        args: list[str] = [
            "curl",
            "-sS",
            "-m",
            str(timeout_s),
            "--connect-timeout",
            "30",
            "-X",
            "POST",
            endpoint,
            "-w",
            "\n%{http_code}",
        ]
        for k, v in headers.items():
            args.extend(["-H", f"{k}: {v}"])
        for i, blob in enumerate(image_blobs):
            p = Path(td) / f"ref_{i}.png"
            await asyncio.to_thread(p.write_bytes, blob)
            args.extend(["-F", f"image=@{p};type=image/png"])
        form = edit_request_fields(prompt, backend, options=options)
        for key, value in form.items():
            args.extend(["--form-string", f"{key}={value}"])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"curl 退出码 {proc.returncode}: {err}")
        raw = stdout.decode("utf-8", errors="replace")
        if "\n" not in raw:
            return 0, raw
        body, code_line = raw.rsplit("\n", 1)
        try:
            return int(code_line.strip()), body
        except ValueError:
            return 0, raw


async def post_edits_with_transport(
    client: httpx.AsyncClient,
    image_blobs: list[bytes],
    prompt: str,
    backend: ImageApiBackend,
    *,
    options: ImageGenRequestOptions | None = None,
    req_timeout_cap: float | None = None,
) -> tuple[int, str]:
    mode = effective_http_transport()
    cfg = image_gen_config
    tcap = req_timeout_cap
    if mode == "curl":
        return await curl_post_edits(image_blobs, prompt, backend, options=options, req_timeout_cap=tcap)
    if mode == "httpx":
        return await httpx_post_edits(client, image_blobs, prompt, backend, options=options, req_timeout_cap=tcap)
    if mode == "cffi":
        return await curl_cffi_post_edits(image_blobs, prompt, backend, options=options, req_timeout_cap=tcap)
    if (cfg.tls_impersonate or "").strip():
        try:
            return await curl_cffi_post_edits(image_blobs, prompt, backend, options=options, req_timeout_cap=tcap)
        except (CffiRequestsError, OSError, ValueError) as e:
            ret = await try_httpx_after_cffi_timeout(
                e,
                tcap,
                lambda cap: httpx_post_edits(
                    client, image_blobs, prompt, backend, options=options, req_timeout_cap=cap
                ),
            )
            if ret is not None:
                return ret
            if cffi_error_is_timeout(e):
                raise
            logger.warning(f"pallas_image edits curl_cffi failed, fallback httpx: {e}")
    try:
        return await httpx_post_edits(client, image_blobs, prompt, backend, options=options, req_timeout_cap=tcap)
    except httpx.ConnectError as e:
        logger.warning(f"pallas_image edits httpx connect failed, fallback curl: {e}")
        return await curl_post_edits(image_blobs, prompt, backend, options=options, req_timeout_cap=tcap)


MIN_GENERATED_IMAGE_BYTES = 64


def is_valid_generated_image(data: bytes) -> bool:
    """校验上游返回的图片字节：magic + 最小长度，过滤 HTML/空包等伪 200。"""
    if not data or len(data) < MIN_GENERATED_IMAGE_BYTES:
        return False
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return True
    return False


def strip_data_url_base64(value: str) -> str:
    """部分网关把 b64_json 填成 data:image/png;base64,...，需去掉前缀再解码。"""
    t = value.strip()
    if t.startswith("data:") and ";base64," in t:
        return t.split(";base64,", 1)[1]
    return t


def decode_inline_image_reference(value: str) -> bytes | None:
    """解析 data:image/...;base64,... 或裸 base64 字段。"""
    t = (value or "").strip()
    if not t:
        return None
    if t.startswith("data:") and ";base64," in t:
        try:
            return base64.b64decode(strip_data_url_base64(t))
        except Exception:
            return None
    return None


def image_bytes_from_payload_field(url: str | None, b64: str | None) -> tuple[str | None, bytes | None]:
    if isinstance(b64, str) and b64.strip():
        try:
            return None, base64.b64decode(strip_data_url_base64(b64))
        except Exception:
            return None, None
    if isinstance(url, str) and url.strip():
        u = url.strip()
        inline = decode_inline_image_reference(u)
        if inline is not None:
            return None, inline
        return u, None
    return None, None


def extract_image_from_generation_payload(data: object) -> tuple[str | None, bytes | None]:
    if not isinstance(data, dict):
        return None, None
    items = data.get("data")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            remote, raw = image_bytes_from_payload_field(first.get("url"), first.get("b64_json"))
            if raw or remote:
                return remote, raw
    inner = data.get("data")
    if isinstance(inner, dict):
        remote, raw = image_bytes_from_payload_field(inner.get("url"), inner.get("b64_json"))
        if raw or remote:
            return remote, raw
    return image_bytes_from_payload_field(
        data.get("url") if isinstance(data.get("url"), str) else None,
        data.get("b64_json") if isinstance(data.get("b64_json"), str) else None,
    )


async def bytes_from_image_reference(
    client: httpx.AsyncClient,
    url: str,
    *,
    download_timeout: float | None = None,
) -> bytes | None:
    u = (url or "").strip()
    if u.startswith("base64://"):
        try:
            return base64.b64decode(u[9:])
        except Exception:
            return None
    if not u.startswith(("http://", "https://")):
        return None
    try:
        r = await client.get(u, timeout=download_timeout)
        if r.status_code == 200:
            return r.content
        logger.debug(
            "download ref image non-200: url={}, status={}",
            u[:160],
            r.status_code,
        )
        return None
    except Exception as exc:
        logger.debug(f"pallas_image download ref image error url={u[:160]!r} exc={exc!r}")
        return None


async def download_reference_images(
    client: httpx.AsyncClient,
    ref_urls: list[str],
    *,
    download_timeout: float | None = None,
) -> list[bytes]:
    if not ref_urls:
        return []
    ref_timeout = download_timeout if download_timeout is not None else image_gen_config.ref_download_timeout

    async def one(url: str) -> bytes | None:
        return await bytes_from_image_reference(client, url, download_timeout=ref_timeout)

    results = await asyncio.gather(*(one(u) for u in ref_urls))
    return [b for b in results if b]


def generations_payload(
    prompt: str,
    ref_urls: list[str],
    *,
    model: str,
    backend: ImageApiBackend,
    options: ImageGenRequestOptions | None = None,
) -> dict[str, object]:
    opts = options or ImageGenRequestOptions.from_config()
    body: dict[str, object] = {
        "model": model,
        "prompt": prompt,
    }
    if opts.size:
        body["size"] = opts.size
    elif opts.aspect_ratio:
        body["aspect_ratio"] = opts.aspect_ratio
    if opts.quality:
        body["quality"] = opts.quality
    if should_send_response_format(backend, opts):
        body["response_format"] = opts.response_format
    merge = image_gen_config.merge_reference_urls_into_prompt
    if ref_urls and not merge and opts.include_ref_images:
        body["image"] = ref_urls
    return body


def message_at_user(user_id: int, tail: str | Message | MessageSegment) -> Message:
    """群内回复前 @ 指定成员，便于指向发起命令的用户。"""
    head = MessageSegment.at(user_id)
    space = MessageSegment.text(" ")
    if isinstance(tail, str):
        return head + space + MessageSegment.text(tail)
    if isinstance(tail, Message):
        return head + space + tail
    return head + space + tail


def optional_message_at_user(
    user_id: int | None, tail: str | Message | MessageSegment
) -> str | Message | MessageSegment:
    if user_id is None:
        return tail
    return message_at_user(user_id, tail)


def image_api_body_issue_label(body_text: str) -> str | None:
    """HTTP 200 时正文是否可发图；不可用时返回简短原因（供日志，不暴露给用户）。"""
    try:
        data = json.loads(body_text)
    except Exception:
        return "invalid_json"
    if not isinstance(data, dict):
        return "invalid_shape"
    if data.get("error") is not None:
        return "upstream_error"
    remote_url, raw = extract_image_from_generation_payload(data)
    if raw:
        return None if is_valid_generated_image(raw) else "invalid_image"
    if remote_url:
        return None
    return "no_image"


async def reply_from_image_api_json(
    matcher,
    client: httpx.AsyncClient,
    body_text: str,
    at_user_id: int | None = None,
    persist_draw: tuple[int, int] | None = None,
    *,
    finish_on_error: bool = True,
) -> bool:
    try:
        data = json.loads(body_text)
    except Exception:
        logger.error(f"pallas_image api invalid json body_prefix={body_text[:500]!r}")
        if finish_on_error:
            await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))
        return False

    if not isinstance(data, dict):
        if finish_on_error:
            await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))
        return False

    if data.get("error") is not None:
        if finish_on_error:
            await matcher.finish(optional_message_at_user(at_user_id, user_failure_reply(body_text)))
        return False

    remote_url, raw = extract_image_from_generation_payload(data)

    async def send_validated_image(image_bytes: bytes) -> bool:
        if not is_valid_generated_image(image_bytes):
            logger.warning(
                f"pallas_image generated image rejected: len={len(image_bytes)} head={image_bytes[:16]!r}",
            )
            return False
        await matcher.send(optional_message_at_user(at_user_id, MessageSegment.image(image_bytes)))
        if persist_draw:
            schedule_persist_generated_draw(image_bytes, persist_draw[0], persist_draw[1])
        return True

    if raw:
        if await send_validated_image(raw):
            return True
        if finish_on_error:
            await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))
        return False
    if remote_url:
        inline = decode_inline_image_reference(remote_url)
        if inline is not None:
            if await send_validated_image(inline):
                return True
            if finish_on_error:
                await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))
            return False
        try:
            img_resp = await client.get(remote_url)
            if img_resp.status_code == 200 and await send_validated_image(img_resp.content):
                return True
        except httpx.HTTPError:
            pass
        logger.error(f"pallas_image download generated image failed url={remote_url}")
        if finish_on_error:
            await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))
        return False
    logger.warning(f"pallas_image response missing image url/b64 data_prefix={str(data)[:800]!r}")
    if finish_on_error:
        await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))
    return False
