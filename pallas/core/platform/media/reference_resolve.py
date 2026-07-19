"""Bot 侧参考图解析：平台 URL → inline data URL，供 draw / AI runtime 共用。"""

from __future__ import annotations

import asyncio
import base64
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from curl_cffi.requests import AsyncSession as CffiAsyncSession
from nonebot import logger

PLATFORM_REFERENCE_HOST_TOKENS = (
    "qpic.cn",
    "qlogo.cn",
    "qq.com",
    "multimedia.nt.qq.com.cn",
)


@dataclass(frozen=True, slots=True)
class ReferenceDownloadOptions:
    user_agent: str = "curl/8.5.0"
    http_transport: str = "auto"
    tls_impersonate: str = "chrome124"
    tls_verify: bool = True
    http_ca_bundle: str = ""
    ref_download_timeout: float = 60.0

    def optional_headers(self) -> dict[str, str]:
        ua = (self.user_agent or "").strip()
        return {"User-Agent": ua} if ua else {}

    def httpx_verify(self) -> bool | str:
        ca = (self.http_ca_bundle or "").strip()
        if ca:
            path = Path(ca)
            if path.is_file():
                return str(path.resolve())
            logger.warning("reference http_ca_bundle 不是有效文件: {}", ca)
        return self.tls_verify

    def curl_ssl_cli_args(self) -> list[str]:
        verify = self.httpx_verify()
        if verify is False:
            return ["-k"]
        if isinstance(verify, str):
            return ["--cacert", verify]
        return []

    def effective_http_transport(self) -> str:
        raw = (self.http_transport or "auto").strip().lower()
        if raw in ("", "auto"):
            return "auto"
        if raw in ("httpx", "curl", "cffi"):
            return raw
        logger.warning("unknown reference http_transport {}, fallback to auto", raw)
        return "auto"


@dataclass(frozen=True, slots=True)
class ReferenceResolveResult:
    inline_urls: list[str] = field(default_factory=list)
    failed_tokens: tuple[str, ...] = ()


def strip_data_url_base64(value: str) -> str:
    t = value.strip()
    if t.startswith("data:") and ";base64," in t:
        return t.split(";base64,", 1)[1]
    return t


def decode_inline_image_reference(value: str) -> bytes | None:
    t = (value or "").strip()
    if not t:
        return None
    if t.startswith("data:") and ";base64," in t:
        try:
            return base64.b64decode(strip_data_url_base64(t))
        except (ValueError, TypeError):
            return None
    return None


def is_inline_reference_token(token: str) -> bool:
    t = (token or "").strip()
    return t.startswith(("data:", "base64://"))


def is_platform_reference_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(token in lower for token in PLATFORM_REFERENCE_HOST_TOKENS)


def bytes_to_data_reference_url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def reference_token_to_bytes(token: str) -> bytes | None:
    u = (token or "").strip()
    if not u:
        return None
    inline = decode_inline_image_reference(u)
    if inline is not None:
        return inline
    if u.startswith("base64://"):
        try:
            return base64.b64decode(u[9:])
        except (ValueError, TypeError):
            return None
    return None


def reference_request_headers(url: str, options: ReferenceDownloadOptions) -> dict[str, str]:
    headers = dict(options.optional_headers())
    if is_platform_reference_url(url):
        headers.setdefault("Referer", "https://qun.qq.com/")
    return headers


async def httpx_get_reference_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    options: ReferenceDownloadOptions,
    download_timeout: float,
) -> bytes | None:
    timeout = httpx.Timeout(download_timeout, connect=min(30.0, download_timeout))
    response = await client.get(url, headers=reference_request_headers(url, options), timeout=timeout)
    if response.status_code == 200 and response.content:
        return response.content
    logger.debug(
        "reference download non-200 url={} status={}",
        url[:160],
        response.status_code,
    )
    return None


async def curl_cffi_get_reference_bytes(
    url: str,
    *,
    options: ReferenceDownloadOptions,
    download_timeout: float,
) -> bytes | None:
    impersonate = (options.tls_impersonate or "").strip()
    if not impersonate:
        raise ValueError("tls_impersonate 为空")
    async with CffiAsyncSession() as session:
        response = await session.get(
            url,
            headers=reference_request_headers(url, options),
            impersonate=impersonate,
            timeout=download_timeout,
            verify=options.tls_verify,
        )
        if response.status_code == 200 and response.content:
            return response.content
    logger.debug("reference cffi non-200 url={} status={}", url[:160], response.status_code)
    return None


async def curl_get_reference_bytes(
    url: str,
    *,
    options: ReferenceDownloadOptions,
    download_timeout: float,
) -> bytes | None:
    if not shutil.which("curl"):
        raise RuntimeError("未找到 curl 可执行文件")
    timeout_s = int(max(5, min(download_timeout, 600)))
    args = [
        "curl",
        "-sS",
        "-L",
        "-m",
        str(timeout_s),
        "--connect-timeout",
        "30",
        "-w",
        "\n%{http_code}",
        url,
    ]
    args.extend(options.curl_ssl_cli_args())
    for key, value in reference_request_headers(url, options).items():
        args.extend(["-H", f"{key}: {value}"])
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"curl 退出码 {proc.returncode}: {err}")
    if b"\n" not in stdout:
        return None
    body, code_line = stdout.rsplit(b"\n", 1)
    try:
        status = int(code_line.strip())
    except ValueError:
        return None
    if status == 200 and body:
        return body
    logger.debug("reference curl non-200 url={} status={}", url[:160], status)
    return None


async def download_reference_bytes_with_transport(
    client: httpx.AsyncClient,
    url: str,
    *,
    options: ReferenceDownloadOptions,
    download_timeout: float,
) -> bytes | None:
    mode = options.effective_http_transport()
    skip_cffi = isinstance(options.httpx_verify(), str)
    if skip_cffi and mode == "cffi":
        mode = "httpx"
    if mode == "httpx":
        try:
            return await httpx_get_reference_bytes(client, url, options=options, download_timeout=download_timeout)
        except Exception as exc:
            logger.debug(f"reference httpx error url={url[:160]!r} exc={exc!r}")
            return None
    if mode == "cffi":
        try:
            return await curl_cffi_get_reference_bytes(url, options=options, download_timeout=download_timeout)
        except Exception as exc:
            logger.warning(f"reference cffi failed, fallback httpx: {exc}")
            try:
                return await httpx_get_reference_bytes(client, url, options=options, download_timeout=download_timeout)
            except Exception as inner:
                logger.debug(f"reference httpx fallback error url={url[:160]!r} exc={inner!r}")
                return None
    if mode == "curl":
        try:
            return await curl_get_reference_bytes(url, options=options, download_timeout=download_timeout)
        except Exception as exc:
            logger.warning(f"reference curl failed, fallback httpx: {exc}")
            try:
                return await httpx_get_reference_bytes(client, url, options=options, download_timeout=download_timeout)
            except Exception as inner:
                logger.debug(f"reference httpx fallback error url={url[:160]!r} exc={inner!r}")
                return None
    if (options.tls_impersonate or "").strip() and not skip_cffi:
        try:
            return await curl_cffi_get_reference_bytes(url, options=options, download_timeout=download_timeout)
        except Exception as exc:
            logger.debug(f"reference auto cffi miss url={url[:160]!r} exc={exc!r}")
    try:
        return await httpx_get_reference_bytes(client, url, options=options, download_timeout=download_timeout)
    except Exception as exc:
        logger.debug(f"reference auto httpx miss url={url[:160]!r} exc={exc!r}")
    try:
        return await curl_get_reference_bytes(url, options=options, download_timeout=download_timeout)
    except Exception as exc:
        logger.debug(f"reference auto curl miss url={url[:160]!r} exc={exc!r}")
    return None


async def resolve_reference_inline_urls(
    client: httpx.AsyncClient,
    ref_urls: list[str],
    *,
    options: ReferenceDownloadOptions,
    download_timeout: float | None = None,
) -> ReferenceResolveResult:
    if not ref_urls:
        return ReferenceResolveResult()
    ref_timeout = download_timeout if download_timeout is not None else options.ref_download_timeout
    inline_urls: list[str] = []
    failed: list[str] = []
    for raw in ref_urls:
        token = (raw or "").strip()
        if not token:
            continue
        blob = reference_token_to_bytes(token)
        if blob is not None:
            inline_urls.append(bytes_to_data_reference_url(blob))
            continue
        if not token.startswith(("http://", "https://")):
            logger.warning("reference unrecognized token={}", token[:80])
            failed.append(token)
            continue
        blob = await download_reference_bytes_with_transport(
            client,
            token,
            options=options,
            download_timeout=ref_timeout,
        )
        if blob is not None:
            inline_urls.append(bytes_to_data_reference_url(blob))
            continue
        logger.warning("reference download failed url={}", token[:160])
        failed.append(token)
    return ReferenceResolveResult(inline_urls=inline_urls, failed_tokens=tuple(failed))


async def bytes_from_reference_token(
    client: httpx.AsyncClient,
    token: str,
    *,
    options: ReferenceDownloadOptions,
    download_timeout: float | None = None,
) -> bytes | None:
    u = (token or "").strip()
    blob = reference_token_to_bytes(u)
    if blob is not None:
        return blob
    if not u.startswith(("http://", "https://")):
        return None
    ref_timeout = download_timeout if download_timeout is not None else options.ref_download_timeout
    try:
        return await download_reference_bytes_with_transport(
            client,
            u,
            options=options,
            download_timeout=ref_timeout,
        )
    except Exception as exc:
        logger.debug(f"reference token download error url={u[:160]!r} exc={exc!r}")
        return None
