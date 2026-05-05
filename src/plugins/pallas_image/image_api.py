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

from .config import image_gen_config


def image_api_base() -> str:
    base = (image_gen_config.base_url or "").strip()
    if not base:
        return ""
    return base if base.endswith("/") else base + "/"


def image_gen_endpoint() -> str:
    b = image_api_base()
    return urljoin(b, "v1/images/generations") if b else ""


def image_edits_endpoint() -> str:
    b = image_api_base()
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


def image_gen_auth_headers_json() -> dict[str, str]:
    cfg = image_gen_config
    h = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    h.update(image_gen_optional_headers())
    return h


def image_gen_auth_headers_multipart() -> dict[str, str]:
    h = {"Authorization": f"Bearer {image_gen_config.api_key}"}
    h.update(image_gen_optional_headers())
    return h


async def httpx_post_generations(url: str, headers: dict[str, str], payload: dict[str, object]) -> tuple[int, str]:
    cfg = image_gen_config
    timeout = httpx.Timeout(cfg.request_timeout)
    async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
        r = await client.post(url, headers=headers, json=payload)
        return r.status_code, r.text


async def curl_cffi_post_generations(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> tuple[int, str]:
    cfg = image_gen_config
    impersonate = (cfg.tls_impersonate or "").strip()
    if not impersonate:
        raise ValueError("tls_impersonate 为空")
    async with CffiAsyncSession() as session:
        r = await session.post(
            url,
            headers=headers,
            json=payload,
            impersonate=impersonate,
            timeout=cfg.request_timeout,
        )
        return r.status_code, r.text


async def curl_post_generations(url: str, headers: dict[str, str], payload: dict[str, object]) -> tuple[int, str]:
    if not shutil.which("curl"):
        raise RuntimeError("未找到 curl 可执行文件，请安装 curl 或将 pallas_image_http_transport 设为 httpx")
    cfg = image_gen_config
    timeout_s = int(max(10, min(cfg.request_timeout, 600)))
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
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> tuple[int, str]:
    mode = effective_http_transport()
    cfg = image_gen_config
    if mode == "curl":
        return await curl_post_generations(url, headers, payload)
    if mode == "httpx":
        return await httpx_post_generations(url, headers, payload)
    if mode == "cffi":
        return await curl_cffi_post_generations(url, headers, payload)
    if (cfg.tls_impersonate or "").strip():
        try:
            return await curl_cffi_post_generations(url, headers, payload)
        except (CffiRequestsError, OSError, ValueError) as e:
            logger.warning("image generations curl_cffi 失败，回退 httpx: {}", e)
    try:
        return await httpx_post_generations(url, headers, payload)
    except httpx.ConnectError as e:
        logger.warning("image generations httpx 连接失败，回退系统 curl: {}", e)
        return await curl_post_generations(url, headers, payload)


async def httpx_post_edits(image_blobs: list[bytes], prompt: str) -> tuple[int, str]:
    cfg = image_gen_config
    endpoint = image_edits_endpoint()
    headers = image_gen_auth_headers_multipart()
    timeout = httpx.Timeout(cfg.request_timeout)
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for i, blob in enumerate(image_blobs):
        files.append(("image", (f"ref_{i}.png", blob, "image/png")))
    data: dict[str, str] = {"prompt": prompt, "model": cfg.model}
    sz = (cfg.size or "").strip()
    if sz:
        data["size"] = sz
    q = (cfg.quality or "").strip()
    if q:
        data["quality"] = q
    rf = (cfg.response_format or "").strip()
    if rf:
        data["response_format"] = rf
    async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
        r = await client.post(endpoint, headers=headers, files=files, data=data)
        return r.status_code, r.text


async def curl_cffi_post_edits(image_blobs: list[bytes], prompt: str) -> tuple[int, str]:
    cfg = image_gen_config
    impersonate = (cfg.tls_impersonate or "").strip()
    if not impersonate:
        raise ValueError("tls_impersonate 为空")
    endpoint = image_edits_endpoint()
    headers = image_gen_auth_headers_multipart()
    mp = CurlMime()
    for i, blob in enumerate(image_blobs):
        mp.addpart("image", data=blob, filename=f"ref_{i}.png", content_type="image/png")
    data: dict[str, str] = {"prompt": prompt, "model": cfg.model}
    sz = (cfg.size or "").strip()
    if sz:
        data["size"] = sz
    q = (cfg.quality or "").strip()
    if q:
        data["quality"] = q
    rf = (cfg.response_format or "").strip()
    if rf:
        data["response_format"] = rf
    async with CffiAsyncSession() as session:
        r = await session.post(
            endpoint,
            headers=headers,
            multipart=mp,
            data=data,
            impersonate=impersonate,
            timeout=cfg.request_timeout,
        )
        return r.status_code, r.text


async def curl_post_edits(image_blobs: list[bytes], prompt: str) -> tuple[int, str]:
    if not shutil.which("curl"):
        raise RuntimeError("未找到 curl 可执行文件")
    cfg = image_gen_config
    endpoint = image_edits_endpoint()
    headers = image_gen_auth_headers_multipart()
    timeout_s = int(max(10, min(cfg.request_timeout, 600)))
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
        args.extend(["--form-string", f"prompt={prompt}", "--form-string", f"model={cfg.model}"])
        sz = (cfg.size or "").strip()
        if sz:
            args.extend(["--form-string", f"size={sz}"])
        q = (cfg.quality or "").strip()
        if q:
            args.extend(["--form-string", f"quality={q}"])
        rf = (cfg.response_format or "").strip()
        if rf:
            args.extend(["--form-string", f"response_format={rf}"])
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


async def post_edits_with_transport(image_blobs: list[bytes], prompt: str) -> tuple[int, str]:
    mode = effective_http_transport()
    cfg = image_gen_config
    if mode == "curl":
        return await curl_post_edits(image_blobs, prompt)
    if mode == "httpx":
        return await httpx_post_edits(image_blobs, prompt)
    if mode == "cffi":
        return await curl_cffi_post_edits(image_blobs, prompt)
    if (cfg.tls_impersonate or "").strip():
        try:
            return await curl_cffi_post_edits(image_blobs, prompt)
        except (CffiRequestsError, OSError, ValueError) as e:
            logger.warning("image edits curl_cffi 失败，回退 httpx: {}", e)
    try:
        return await httpx_post_edits(image_blobs, prompt)
    except httpx.ConnectError as e:
        logger.warning("image edits httpx 连接失败，回退系统 curl: {}", e)
        return await curl_post_edits(image_blobs, prompt)


def extract_image_from_generation_payload(data: object) -> tuple[str | None, bytes | None]:
    if not isinstance(data, dict):
        return None, None
    items = data.get("data")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            u = first.get("url")
            if isinstance(u, str) and u.strip():
                return u.strip(), None
            b64 = first.get("b64_json")
            if isinstance(b64, str) and b64.strip():
                try:
                    return None, base64.b64decode(b64)
                except Exception:
                    return None, None
    inner = data.get("data")
    if isinstance(inner, dict):
        u = inner.get("url")
        if isinstance(u, str) and u.strip():
            return u.strip(), None
    u = data.get("url")
    if isinstance(u, str) and u.strip():
        return u.strip(), None
    return None, None


async def bytes_from_image_reference(client: httpx.AsyncClient, url: str) -> bytes | None:
    u = (url or "").strip()
    if u.startswith("base64://"):
        try:
            return base64.b64decode(u[9:])
        except Exception:
            return None
    if not u.startswith(("http://", "https://")):
        return None
    try:
        r = await client.get(u)
        if r.status_code == 200:
            return r.content
        logger.debug(
            "download ref image non-200: url={}, status={}",
            u[:160],
            r.status_code,
        )
        return None
    except Exception as exc:
        logger.debug("download ref image error: url={}, exc={!r}", u[:160], exc)
        return None


def generations_payload(prompt: str, ref_urls: list[str]) -> dict[str, object]:
    cfg = image_gen_config
    body: dict[str, object] = {
        "model": cfg.model,
        "prompt": prompt,
    }
    sz = (cfg.size or "").strip()
    ar = (cfg.aspect_ratio or "").strip()
    if sz:
        body["size"] = sz
    elif ar:
        body["aspect_ratio"] = ar
    q = (cfg.quality or "").strip()
    if q:
        body["quality"] = q
    rf = (cfg.response_format or "").strip()
    if rf:
        body["response_format"] = rf
    merge = cfg.merge_reference_urls_into_prompt
    if ref_urls and not merge:
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


async def reply_from_image_api_json(
    matcher,
    client: httpx.AsyncClient,
    body_text: str,
    at_user_id: int | None = None,
) -> None:
    try:
        data = json.loads(body_text)
    except Exception:
        logger.error("image api invalid json: {}", body_text[:500])
        await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))

    if not isinstance(data, dict):
        await matcher.finish(optional_message_at_user(at_user_id, PALLAS_VAGUE_REPLY))

    if data.get("error") is not None:
        await matcher.finish(optional_message_at_user(at_user_id, user_failure_reply(body_text)))

    remote_url, raw = extract_image_from_generation_payload(data)
    if raw:
        await matcher.send(optional_message_at_user(at_user_id, MessageSegment.image(raw)))
        return
    if remote_url:
        try:
            img_resp = await client.get(remote_url)
            if img_resp.status_code == 200:
                await matcher.send(optional_message_at_user(at_user_id, MessageSegment.image(img_resp.content)))
                return
        except httpx.HTTPError:
            pass
        logger.error("download generated image failed: url={}", remote_url)
        await matcher.send(PALLAS_VAGUE_REPLY)
        return
    logger.warning("image api no url/b64 in response: {}", str(data)[:800])
    await matcher.finish(PALLAS_VAGUE_REPLY)
