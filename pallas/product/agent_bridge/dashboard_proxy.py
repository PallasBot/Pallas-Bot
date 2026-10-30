"""Same-origin, Pallas-session-gated proxy for the managed MaiBot dashboard."""

from __future__ import annotations

import asyncio
import email.utils
import ipaddress
import re
import tomllib
from dataclasses import dataclass, field
from datetime import UTC
from http.cookies import CookieError, SimpleCookie
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote_to_bytes, urlsplit

import aiohttp
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState
from yarl import URL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from fastapi import FastAPI
    from starlette.requests import Request

PREFIX = "/pallas/maibot"
PALLAS_SESSION_COOKIE = "pallas_console_session"
NATIVE_SESSION_COOKIE = "pallas_maibot_session"
UPSTREAM_SESSION_COOKIE = "maibot_session"
MAX_REQUEST_BODY_BYTES = 101 * 1024 * 1024
MAX_WEBSOCKET_MESSAGE_BYTES = 4 * 1024 * 1024
WS_REAUTH_INTERVAL_SEC = 5.0
_HTTP_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_SAFE_METHODS = {"GET", "HEAD"}
_WS_PATHS = {f"{PREFIX}/api/webui/ws", f"{PREFIX}/ws/logs"}
_STATIC_RESOURCE_SUFFIXES = (".ico", ".js", ".css", ".map", ".woff2", ".woff", ".ttf")
_DROP_RESPONSE_HEADERS = {"clear-site-data", "service-worker-allowed", "refresh"}
_REQUEST_HEADERS = {
    "accept",
    "accept-encoding",
    "accept-language",
    "cache-control",
    "content-type",
    "if-match",
    "if-modified-since",
    "if-none-match",
    "if-range",
    "if-unmodified-since",
    "pragma",
    "range",
    "user-agent",
}
_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_COOKIE_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_COOKIE_VALUE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z=%:/?@\[\]{}]*$")
_MAX_WS_CLOSE = 4999


class _InvalidPathError(ValueError):
    pass


class _BodyTooLargeError(ValueError):
    pass


class _RedirectBlockedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Target:
    host: str
    port: int

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


@dataclass(slots=True)
class DashboardProxyState:
    app: FastAPI
    target_resolver: Callable[[], object] | None = None
    process_provider: Callable[[], object] | None = None
    session_verifier: Callable[[str | None], bool] | None = None
    session: aiohttp.ClientSession | None = None
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def client(self) -> aiohttp.ClientSession:
        if self.session is not None and not self.session.closed:
            return self.session
        async with self.session_lock:
            if self.session is None or self.session.closed:
                trace = aiohttp.TraceConfig()

                async def block_redirect(
                    _session: aiohttp.ClientSession,
                    _context: object,
                    _params: aiohttp.TraceRequestRedirectParams,
                ) -> None:
                    raise _RedirectBlockedError

                trace.on_request_redirect.append(block_redirect)
                self.session = aiohttp.ClientSession(
                    trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(),
                    auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=180, sock_connect=2, sock_read=60),
                    skip_auto_headers={"User-Agent"},
                    trace_configs=[trace],
                )
        return self.session

    async def close(self) -> None:
        session, self.session = self.session, None
        if session is not None and not session.closed:
            await session.close()

    def process_id(self) -> int | None:
        try:
            value = (self.process_provider or _current_managed_process)()
        except Exception:  # noqa: BLE001
            return None
        return value if type(value) is int and value > 0 else None

    def target(self) -> _Target | None:
        try:
            value = self.target_resolver() if self.target_resolver else _configured_target()
        except Exception:  # noqa: BLE001
            return None
        return _validate_target(value)

    def session_ok(self, token: str | None) -> bool:
        try:
            verifier = self.session_verifier or _verify_pallas_session
            return bool(verifier(token))
        except (TypeError, ValueError):
            return False


def _current_managed_process() -> object:
    from pallas.console.cli import maibot_aux

    return maibot_aux.current_managed_process()


def _configured_target() -> tuple[str, int] | None:
    from pallas.console.cli import maibot_aux

    managed = maibot_aux.load_managed_config()
    if not managed.enabled or managed.instance_dir is None:
        return None
    config_path = managed.instance_dir / "config" / "bot_config.toml"
    with config_path.open("rb") as config_file:
        document = tomllib.load(config_file)
    webui = document.get("webui", {})
    if not isinstance(webui, dict) or webui.get("enabled", True) is not True:
        return None
    if "host" in webui and "hosts" in webui:
        return None
    hosts = webui.get("host", webui.get("hosts", ["127.0.0.1", "::1"]))
    if isinstance(hosts, str):
        hosts = [hosts]
    if (
        not isinstance(hosts, list)
        or not hosts
        or any(not isinstance(host, str) or host not in {"127.0.0.1", "::1"} for host in hosts)
    ):
        return None
    port = webui.get("port", 8001)
    if type(port) is not int or not 1 <= port <= 65535:
        return None
    host = "127.0.0.1" if "127.0.0.1" in hosts else "::1"
    return host, port


def _validate_target(value: object) -> _Target | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    host, port = value
    if host not in {"127.0.0.1", "::1"} or type(port) is not int or not 1 <= port <= 65535:
        return None
    try:
        if not ipaddress.ip_address(host).is_loopback:
            return None
    except ValueError:
        return None
    return _Target(host, port)


def _verify_pallas_session(token: str | None) -> bool:
    from pallas.console.webui import console_login

    return console_login.verify_session_token(token)


def _raw_headers(scope: dict[str, Any], name: str) -> list[str]:
    key = name.lower().encode("ascii")
    return [value.decode("latin-1") for header, value in scope.get("headers", ()) if header.lower() == key]


def _parse_cookies(scope: dict[str, Any]) -> tuple[str | None, str | None]:
    found: dict[str, list[str]] = {PALLAS_SESSION_COOKIE: [], NATIVE_SESSION_COOKIE: []}
    for header in _raw_headers(scope, "cookie"):
        for part in header.split(";"):
            name, separator, value = part.strip().partition("=")
            if not separator:
                if name.strip().lower() in {key.lower() for key in found}:
                    raise ValueError("ambiguous cookie")
                continue
            lowered = name.strip().lower()
            matched = next((key for key in found if key.lower() == lowered), None)
            if matched is None:
                continue
            name, value = name.strip(), value.strip()
            if name != matched or not _COOKIE_TOKEN.fullmatch(name) or not _COOKIE_VALUE.fullmatch(value):
                raise ValueError("ambiguous cookie")
            found[matched].append(value)
    if any(len(values) > 1 for values in found.values()):
        raise ValueError("duplicate cookie")
    console_token = found[PALLAS_SESSION_COOKIE][0] if found[PALLAS_SESSION_COOKIE] else None
    native_cookie = found[NATIVE_SESSION_COOKIE][0] if found[NATIVE_SESSION_COOKIE] else None
    if native_cookie and (native_cookie == console_token or native_cookie.startswith("pls_")):
        raise ValueError("ambiguous cookie")
    return console_token, native_cookie


def _normalized_origin(value: str, *, origin_only: bool) -> tuple[str, str, int] | None:
    if not value or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value):
        return None
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            return None
        if parsed.password is not None or parsed.fragment:
            return None
        if origin_only and (parsed.path not in {"", "/"} or parsed.query):
            return None
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port or (443 if scheme == "https" else 80)
    except (UnicodeError, ValueError):
        return None
    return scheme, host, port


def _request_origin(scope: dict[str, Any]) -> tuple[str, str, int] | None:
    scheme = str(scope.get("scheme", "")).lower()
    if scope.get("type") == "websocket":
        scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
    if scheme not in {"http", "https"}:
        return None
    hosts = _raw_headers(scope, "host")
    if len(hosts) > 1:
        return None
    if hosts:
        return _normalized_origin(f"{scheme}://{hosts[0]}", origin_only=True)
    server = scope.get("server")
    if not isinstance(server, (tuple, list)) or len(server) < 2:
        return None
    host, port = server[0], server[1]
    if not isinstance(host, str) or type(port) is not int:
        return None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return _normalized_origin(f"{scheme}://{host}:{port}", origin_only=True)


def _browser_secure(scope: dict[str, Any]) -> bool:
    return scope.get("scheme") in {"https", "wss"}


def _same_origin(value: str, expected: tuple[str, str, int] | None, *, origin_only: bool) -> bool:
    return expected is not None and _normalized_origin(value, origin_only=origin_only) == expected


def _origin_allowed(scope: dict[str, Any], *, websocket: bool, method: str = "GET") -> bool:
    origins = _raw_headers(scope, "origin")
    expected = _request_origin(scope)
    if websocket:
        return len(origins) == 1 and _same_origin(origins[0], expected, origin_only=True)
    if len(origins) > 1:
        return False
    if origins:
        return _same_origin(origins[0], expected, origin_only=True)
    if method.upper() in _SAFE_METHODS:
        return True
    referers = _raw_headers(scope, "referer")
    sites = _raw_headers(scope, "sec-fetch-site")
    return (
        len(referers) == 1
        and len(sites) <= 1
        and (not sites or sites[0].strip().lower() != "cross-site")
        and _same_origin(referers[0], expected, origin_only=False)
    )


def _decode_path(value: str) -> str:
    try:
        return unquote_to_bytes(value).decode("utf-8", "strict")
    except UnicodeError as exc:
        raise _InvalidPathError from exc


def _validate_path_value(path: str) -> None:
    current = path
    for _ in range(3):
        if (
            re.search(r"%(?:2f|5c)", current, re.IGNORECASE)
            or "\\" in current
            or "//" in current
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in current)
        ):
            raise _InvalidPathError
        if any(segment in {".", ".."} for segment in current.split("/")):
            raise _InvalidPathError
        current = _decode_path(current)


def _strip_prefix(scope: dict[str, Any], decoded_path: str) -> str:
    raw_path = scope.get("raw_path")
    if not isinstance(raw_path, bytes):
        raw_path = decoded_path.encode("utf-8")
    try:
        raw = raw_path.decode("ascii")
        decoded_once = _decode_path(raw)
    except (UnicodeError, _InvalidPathError) as exc:
        raise _InvalidPathError from exc
    if decoded_once != decoded_path or not (raw == PREFIX or raw.startswith(f"{PREFIX}/")):
        raise _InvalidPathError
    _validate_path_value(raw)
    if raw == PREFIX:
        return "/"
    return raw[len(PREFIX) :] or "/"


def _safe_query(scope: dict[str, Any], *, websocket: bool) -> str:
    raw = scope.get("query_string", b"")
    if not isinstance(raw, bytes):
        raise _InvalidPathError
    try:
        query = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _InvalidPathError from exc
    if any(char in query for char in "\r\n\x00"):
        raise _InvalidPathError
    for _ in range(2):
        try:
            decoded = _decode_path(query.replace("+", " "))
        except _InvalidPathError as exc:
            raise _InvalidPathError from exc
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded):
            raise _InvalidPathError
        query = decoded
    raw_query = raw.decode("ascii")
    forbidden = {
        "pallas_console_session",
        "pallas_session",
        "pallas_token",
        "pallas_webui_page_token",
        "api_key",
        "apikey",
        "x-pallas-api-key",
        "authorization",
    }
    if not websocket:
        forbidden.add("token")
    for pair in raw_query.split("&"):
        name = pair.partition("=")[0].replace("+", " ")
        for _ in range(3):
            if name.casefold() in forbidden:
                raise _InvalidPathError
            name = _decode_path(name)
    return raw.decode("ascii")


def _upstream_url(target: _Target, path: str, query: str, *, websocket: bool = False) -> URL:
    scheme = "ws" if websocket else "http"
    host = f"[{target.host}]" if ":" in target.host else target.host
    url = f"{scheme}://{host}:{target.port}{path}"
    if query:
        url += f"?{query}"
    return URL(url, encoded=True)


def _connection_tokens(headers: list[tuple[bytes, bytes]]) -> set[str]:
    return {
        token.strip().lower()
        for name, value in headers
        if name.lower() == b"connection"
        for token in value.decode("latin-1").split(",")
        if token.strip()
    }


def _outbound_headers(
    scope: dict[str, Any], target: _Target, native_cookie: str | None, *, websocket: bool = False
) -> list[tuple[str, str]]:
    raw_headers = [(name.lower(), value) for name, value in scope.get("headers", ())]
    blocked = _HOP_HEADERS | _connection_tokens(raw_headers)
    allowed = {"user-agent", "sec-websocket-protocol"} if websocket else _REQUEST_HEADERS
    result: list[tuple[str, str]] = []
    for name, value in raw_headers:
        key = name.decode("ascii", "ignore")
        if key in allowed and key not in blocked:
            result.append((key, value.decode("latin-1")))
    if native_cookie is not None and "cookie" not in blocked:
        result.append(("Cookie", f"{UPSTREAM_SESSION_COOKIE}={native_cookie}"))
    if "origin" not in blocked and (websocket or _raw_headers(scope, "origin")):
        result.append(("Origin", target.origin))
    source_origin = _request_origin(scope)
    if source_origin is not None and "x-forwarded-proto" not in blocked:
        result.append(("X-Forwarded-Proto", source_origin[0]))
    return result


def _websocket_protocols(headers: list[tuple[str, str]]) -> list[str]:
    return [
        protocol.strip()
        for name, value in headers
        if name.lower() == "sec-websocket-protocol"
        for protocol in value.split(",")
        if protocol.strip()
    ]


def _response_cookie(header: str, *, browser_secure: bool) -> str | None:
    if "\r" in header or "\n" in header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except (CookieError, TypeError, ValueError):
        return None
    if len(cookie) != 1 or UPSTREAM_SESSION_COOKIE not in cookie:
        return None
    morsel = cookie[UPSTREAM_SESSION_COOKIE]
    value = morsel.value
    if not _COOKIE_VALUE.fullmatch(value):
        return None
    same_site = "Strict" if morsel["samesite"].lower() == "strict" else "Lax"
    parts = [f"{NATIVE_SESSION_COOKIE}={value}", f"Path={PREFIX}/", "HttpOnly", f"SameSite={same_site}"]
    max_age = morsel["max-age"]
    if max_age:
        if not re.fullmatch(r"-?\d+", max_age):
            return None
        parts.append(f"Max-Age={max_age}")
    expires = morsel["expires"]
    if expires:
        try:
            date = email.utils.parsedate_to_datetime(expires)
            if date is None or date.utcoffset() is None:
                return None
            date = date.astimezone(UTC)
            parts.append(f"Expires={email.utils.format_datetime(date, usegmt=True)}")
        except (TypeError, ValueError, OverflowError):
            return None
    if morsel["secure"] or browser_secure:
        parts.append("Secure")
    return "; ".join(parts)


def _rewrite_location(value: str, target: _Target) -> str | None:
    if not value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if value.startswith("//"):
        return None
    if parsed.scheme or parsed.netloc:
        expected = _normalized_origin(target.origin, origin_only=True)
        if (
            parsed.scheme.lower() != "http"
            or _normalized_origin(f"{parsed.scheme}://{parsed.netloc}", origin_only=True) != expected
        ):
            return None
        path = parsed.path or "/"
    else:
        if not value.startswith("/"):
            return None
        path = parsed.path
    try:
        _validate_path_value(path)
    except _InvalidPathError:
        return None
    if not path.startswith("/"):
        return None
    suffix = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{PREFIX}{path}{suffix}{fragment}"


def _response_headers(response: aiohttp.ClientResponse, *, browser_secure: bool) -> list[tuple[bytes, bytes]] | None:
    raw = list(response.raw_headers)
    blocked = _HOP_HEADERS | _connection_tokens(raw)
    locations = [value.decode("latin-1") for name, value in raw if name.lower() == b"location"]
    location = None
    if locations:
        if len(locations) != 1:
            return None
        target = _validate_target((response.url.host, response.url.port or 80))
        if target is None:
            return None
        location = _rewrite_location(locations[0], target)
        if location is None:
            return None
    result: list[tuple[bytes, bytes]] = []
    for name, value in raw:
        lower = name.lower()
        if (
            lower in blocked
            or lower.decode("latin-1") in _DROP_RESPONSE_HEADERS
            or lower == b"location"
            or lower.startswith(b"access-control-")
        ):
            continue
        if lower == b"set-cookie":
            mapped = _response_cookie(value.decode("latin-1"), browser_secure=browser_secure)
            if mapped is not None:
                result.append((b"set-cookie", mapped.encode("latin-1")))
            continue
        result.append((lower, value))
    if location is not None:
        result.append((b"location", location.encode("latin-1")))
    return result


def _json_error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"detail": code}, status_code=status_code)


def _spa_fallback_status(path: str, method: str, response: aiohttp.ClientResponse) -> int | None:
    media_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
    if method not in _SAFE_METHODS or response.status != 200 or media_type != "text/html":
        return None
    lowered_path = path.lower()
    if lowered_path.startswith(("/assets/", "/fonts/")) or lowered_path.endswith(_STATIC_RESOURCE_SUFFIXES):
        return 404
    if lowered_path == "/api" or lowered_path.startswith("/api/"):
        return 502
    return None


def _login_redirect(path: str) -> RedirectResponse:
    try:
        internal_path = f"{PREFIX}{path if path.startswith('/') else '/'}"
        if not internal_path.startswith(f"{PREFIX}/") and internal_path != PREFIX:
            internal_path = f"{PREFIX}/"
        next_path = quote(internal_path, safe="")
    except Exception:  # noqa: BLE001
        next_path = quote(f"{PREFIX}/", safe="")
    return RedirectResponse(f"/pallas/login?next={next_path}", status_code=307)


async def _body_stream(request: Request, declared_length: int | None) -> AsyncIterator[bytes]:
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_REQUEST_BODY_BYTES:
            raise _BodyTooLargeError
        yield chunk
    if declared_length is not None and total != declared_length:
        raise ValueError("request body length mismatch")


async def _proxy_http(state: DashboardProxyState, request: Request) -> Any:
    method = request.method.upper()
    try:
        console_token, native_cookie = _parse_cookies(request.scope)
    except ValueError:
        return _json_error("invalid_cookie", 400)
    if not state.session_ok(console_token):
        api_path = request.url.path in {f"{PREFIX}/api", f"{PREFIX}/api/"} or request.url.path.startswith(
            f"{PREFIX}/api/"
        )
        if method in _SAFE_METHODS and not api_path:
            try:
                path = _strip_prefix(request.scope, request.url.path)
            except _InvalidPathError:
                path = "/"
            return _login_redirect(path)
        return _json_error("unauthorized", 401)
    if not _origin_allowed(request.scope, websocket=False, method=method):
        return _json_error("forbidden", 403)
    try:
        path = _strip_prefix(request.scope, request.url.path)
        query = _safe_query(request.scope, websocket=False)
    except _InvalidPathError:
        return _json_error("invalid_path", 400)
    if request.url.path == PREFIX and method in _SAFE_METHODS:
        return RedirectResponse(f"{PREFIX}/{f'?{query}' if query else ''}", status_code=307)
    raw_lengths = _raw_headers(request.scope, "content-length")
    if len(raw_lengths) > 1:
        return _json_error("invalid_request", 400)
    declared_length: int | None = None
    if raw_lengths:
        raw_length = raw_lengths[0]
        if not raw_length.isascii() or not raw_length.isdecimal():
            return _json_error("invalid_request", 400)
        if len(raw_length) > 20:
            return _json_error("request_too_large", 413)
        declared_length = int(raw_length)
        if declared_length > MAX_REQUEST_BODY_BYTES:
            return _json_error("request_too_large", 413)
    transfer_encoding = _raw_headers(request.scope, "transfer-encoding")
    if transfer_encoding and raw_lengths:
        return _json_error("invalid_request", 400)
    process_id, target = state.process_id(), state.target()
    if process_id is None or target is None:
        return _json_error("maibot_unavailable", 503)
    headers = _outbound_headers(request.scope, target, native_cookie)
    has_body = bool(
        (declared_length or 0) > 0
        or transfer_encoding
        or method in {"POST", "PUT", "PATCH", "DELETE"}
        and declared_length is None
    )
    if declared_length is not None:
        headers.append(("Content-Length", str(declared_length)))
    body = _body_stream(request, declared_length) if has_body else None
    client = await state.client()
    upstream: aiohttp.ClientResponse | None = None
    too_large = False
    try:
        if body is not None:
            original_stream = body

            async def measured_body() -> AsyncIterator[bytes]:
                nonlocal too_large
                try:
                    async for chunk in original_stream:
                        yield chunk
                except _BodyTooLargeError:
                    too_large = True
                    raise

            body = measured_body()
        upstream = await client.request(
            method,
            _upstream_url(target, path, query),
            headers=headers,
            data=body,
            allow_redirects=False,
        )
        fallback_status = _spa_fallback_status(path, method, upstream)
        if fallback_status is not None:
            upstream.close()
            error = "resource_not_found" if fallback_status == 404 else "invalid_api_response"
            return _json_error(error, fallback_status)
        response_headers = _response_headers(upstream, browser_secure=_browser_secure(request.scope))
        if response_headers is None:
            upstream.close()
            return _json_error("invalid_upstream_response", 502)
        if method == "HEAD":
            status_code = upstream.status
            upstream_status = upstream
            upstream = None
            upstream_status.close()
            response = StreamingResponse(iter(()), status_code=status_code)
        else:
            response_upstream = upstream

            async def response_body() -> AsyncIterator[bytes]:
                try:
                    async for chunk in response_upstream.content.iter_chunked(64 * 1024):
                        yield chunk
                finally:
                    response_upstream.close()

            response = StreamingResponse(response_body(), status_code=response_upstream.status)
            upstream = None
        response.raw_headers = response_headers
        return response
    except asyncio.CancelledError:
        if upstream is not None:
            upstream.close()
        raise
    except _RedirectBlockedError:
        if upstream is not None:
            upstream.close()
        return _json_error("invalid_upstream_response", 502)
    except Exception as exc:  # noqa: BLE001
        if upstream is not None:
            upstream.close()
        if too_large or isinstance(exc, _BodyTooLargeError):
            return _json_error("request_too_large", 413)
        if isinstance(exc, (aiohttp.ClientConnectorError, asyncio.TimeoutError)):
            return _json_error("maibot_unavailable", 503 if isinstance(exc, aiohttp.ClientConnectorError) else 504)
        return _json_error("upstream_unavailable", 502)


async def _deny_websocket(websocket: WebSocket, status_code: int, detail: str) -> None:
    await websocket.send_denial_response(PlainTextResponse(detail, status_code=status_code))


def _close_code(value: object, fallback: int = 1001) -> int:
    if type(value) is not int:
        return fallback
    if 1000 <= value <= 1014 and value not in {1004, 1005, 1006}:
        return value
    if 3000 <= value <= _MAX_WS_CLOSE:
        return value
    return fallback


async def _proxy_websocket(state: DashboardProxyState, websocket: WebSocket) -> None:
    try:
        console_token, native_cookie = _parse_cookies(websocket.scope)
    except ValueError:
        await _deny_websocket(websocket, 403, "forbidden")
        return
    if not state.session_ok(console_token):
        await _deny_websocket(websocket, 403, "forbidden")
        return
    if not _origin_allowed(websocket.scope, websocket=True):
        await _deny_websocket(websocket, 403, "forbidden")
        return
    try:
        path = _strip_prefix(websocket.scope, websocket.url.path)
        if f"{PREFIX}{path}" not in _WS_PATHS:
            raise _InvalidPathError
        query = _safe_query(websocket.scope, websocket=True)
    except _InvalidPathError:
        await _deny_websocket(websocket, 400, "invalid_path")
        return
    initial_process = state.process_id()
    target = state.target()
    if initial_process is None or target is None:
        await _deny_websocket(websocket, 503, "maibot_unavailable")
        return
    headers = _outbound_headers(websocket.scope, target, native_cookie, websocket=True)
    client = await state.client()
    native: aiohttp.ClientWebSocketResponse | None = None
    try:
        protocols = _websocket_protocols(headers)
        native = await client.ws_connect(
            _upstream_url(target, path, query, websocket=True),
            headers=headers,
            protocols=protocols,
            origin=target.origin if any(name.lower() == "origin" for name, _ in headers) else None,
            proxy=None,
            compress=0,
            heartbeat=30,
            max_msg_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        )
    except aiohttp.WSServerHandshakeError as exc:
        await _deny_websocket(websocket, exc.status if exc.status in {401, 403} else 502, "upstream_unavailable")
        return
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        await _deny_websocket(websocket, 502, "upstream_unavailable")
        return

    if not state.session_ok(console_token):
        await native.close(code=1008)
        await _deny_websocket(websocket, 403, "forbidden")
        return
    if state.process_id() != initial_process or state.target() != target:
        await native.close(code=1008)
        await _deny_websocket(websocket, 503, "maibot_unavailable")
        return

    cookies = [
        (b"set-cookie", mapped.encode("latin-1"))
        for name, value in native._response.raw_headers
        if name.lower() == b"set-cookie"
        if (mapped := _response_cookie(value.decode("latin-1"), browser_secure=_browser_secure(websocket.scope)))
        is not None
    ]
    await websocket.accept(subprotocol=native.protocol, headers=cookies)

    async def browser_to_native() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    await native.close(code=_close_code(message.get("code")))
                    return
                text, data = message.get("text"), message.get("bytes")
                if text is not None:
                    if len(text.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                        await websocket.close(code=1009)
                        await native.close(code=1009)
                        return
                    await native.send_str(text)
                elif data is not None:
                    if len(data) > MAX_WEBSOCKET_MESSAGE_BYTES:
                        await websocket.close(code=1009)
                        await native.close(code=1009)
                        return
                    await native.send_bytes(data)
        except WebSocketDisconnect as exc:
            await native.close(code=_close_code(exc.code))

    reauth_close_code = 1001

    async def native_to_browser() -> None:
        pending = asyncio.create_task(native.receive())
        try:
            while True:
                await asyncio.wait({pending})
                message = pending.result()
                if message.type == aiohttp.WSMsgType.TEXT:
                    await websocket.send_text(message.data)
                elif message.type == aiohttp.WSMsgType.BINARY:
                    await websocket.send_bytes(message.data)
                elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
                    close_code = reauth_close_code if reauth_close_code != 1001 else _close_code(native.close_code)
                    await websocket.close(code=close_code)
                    return
                elif message.type == aiohttp.WSMsgType.ERROR:
                    await websocket.close(code=1011)
                    return
                pending = asyncio.create_task(native.receive())
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def reauth_watchdog() -> None:
        nonlocal reauth_close_code
        while True:
            await asyncio.sleep(WS_REAUTH_INTERVAL_SEC)
            if not state.session_ok(console_token):
                reauth_close_code = 1008
                await native.close(code=1008)
                return
            if state.process_id() != initial_process or state.target() != target:
                reauth_close_code = 1008
                await native.close(code=1008)
                return

    tasks = [
        asyncio.create_task(browser_to_native()),
        asyncio.create_task(native_to_browser()),
        asyncio.create_task(reauth_watchdog()),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled():
                task.exception()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not native.closed:
            await native.close(code=reauth_close_code)
        if websocket.application_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=reauth_close_code)
            except (RuntimeError, WebSocketDisconnect):
                pass


def register_dashboard_proxy(
    app: FastAPI,
    *,
    target_resolver: Callable[[], object] | None = None,
    process_provider: Callable[[], object] | None = None,
    session_verifier: Callable[[str | None], bool] | None = None,
) -> DashboardProxyState:
    """Register the fixed MaiBot dashboard proxy once for a FastAPI app."""
    existing = getattr(app.state, "maibot_dashboard_proxy", None)
    if isinstance(existing, DashboardProxyState):
        return existing
    state = DashboardProxyState(
        app=app,
        target_resolver=target_resolver,
        process_provider=process_provider,
        session_verifier=session_verifier,
    )
    app.state.maibot_dashboard_proxy = state

    async def proxy_http(request: Request) -> Any:
        return await _proxy_http(state, request)

    async def proxy_websocket(websocket: WebSocket) -> None:
        await _proxy_websocket(state, websocket)

    app.add_route(PREFIX, proxy_http, methods=_HTTP_METHODS)
    app.add_route(f"{PREFIX}/{{path:path}}", proxy_http, methods=_HTTP_METHODS)
    for path in sorted(_WS_PATHS):
        app.add_api_websocket_route(path, proxy_websocket)
    app.router.add_event_handler("shutdown", state.close)
    return state


__all__ = ["DashboardProxyState", "register_dashboard_proxy"]
