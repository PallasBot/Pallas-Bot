from __future__ import annotations

import asyncio
import gzip
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from aiohttp import WSMsgType, web
from fastapi import FastAPI
from starlette.testclient import TestClient, WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from pallas.product.agent_bridge import dashboard_proxy as proxy

if TYPE_CHECKING:
    from collections.abc import Iterator

_SESSION = "valid-pallas-session"
_COOKIE = "pallas_console_session"
_NATIVE_COOKIE = "pallas_maibot_session"


@pytest.fixture
def loopback_native() -> Iterator[dict[str, object]]:
    state: dict[str, object] = {
        "requests": [],
        "ws_cookies": [],
        "ws_headers": [],
        "ws_ticks": 0,
        "ws_tokens": [],
    }
    loop = asyncio.new_event_loop()
    started = threading.Event()
    thread_error: list[BaseException] = []

    async def echo(request: web.Request) -> web.StreamResponse:
        body = await request.read()
        rows = state["requests"]
        assert isinstance(rows, list)
        rows.append({
            "path": request.path,
            "query": request.query_string,
            "method": request.method,
            "body": body,
            "headers": dict(request.headers),
        })
        if request.path == "/redirect-internal":
            return web.Response(status=302, headers={"Location": "/ui/login?next=dashboard"})
        if request.path == "/redirect-external":
            return web.Response(status=302, headers={"Location": "https://example.invalid/out"})
        if request.path == "/status401":
            return web.Response(status=401, text="native login required")
        if request.path == "/compressed":
            return web.Response(
                body=gzip.compress(b"native compressed response"),
                headers={"Content-Encoding": "gzip", "Content-Type": "application/octet-stream"},
            )
        if request.path.endswith(proxy._STATIC_RESOURCE_SUFFIXES) or request.path in {
            "/assets/missing.png",
            "/fonts/missing.txt",
        }:
            return web.Response(text="<html>spa shell</html>", content_type="text/html")
        if request.path == "/api/not-real":
            return web.Response(text="<html>spa shell</html>", content_type="text/html")
        if request.path == "/config/model":
            return web.Response(text="<html>spa shell</html>", content_type="text/html")
        if request.path == "/maibot_statistics.html":
            return web.Response(status=404, text="native statistics route not found")
        if request.path == "/sensitive-headers":
            return web.Response(
                body=b"native resource",
                headers={
                    "Clear-Site-Data": '"cookies"',
                    "Service-Worker-Allowed": "/",
                    "Refresh": "0; url=https://example.invalid/",
                    "ETag": '"native-v1"',
                },
            )
        if request.path == "/cookies":
            response = web.Response(text="cookies")
            response.headers.add(
                "Set-Cookie", "maibot_session=native-one; Domain=example.invalid; Path=/; SameSite=None"
            )
            response.headers.add("Set-Cookie", "pallas_console_session=must-not-escape; Path=/")
            response.headers.add("Set-Cookie", "other_cookie=discard-me; Path=/")
            return response
        if request.path == "/delete-cookie":
            response = web.Response(text="deleted")
            response.headers.add(
                "Set-Cookie",
                "maibot_session=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/",
            )
            return response
        if request.path == "/redirect-ws":
            return web.Response(status=302, headers={"Location": "http://example.invalid/ws"})
        if request.path == "/slow":
            response = web.StreamResponse(headers={"Content-Type": "text/plain"})
            await response.prepare(request)
            try:
                await response.write(b"first")
                await asyncio.sleep(0.2)
                await response.write(b"second")
                await response.write_eof()
            except (ConnectionResetError, RuntimeError):
                disconnect_seen = state.get("disconnect_seen")
                if isinstance(disconnect_seen, threading.Event):
                    disconnect_seen.set()
            return response
        response = web.Response(body=body, headers={"X-Native-Status": "passed"})
        return response

    async def websocket(request: web.Request) -> web.StreamResponse:
        token = request.query.get("token", "")
        tokens = state["ws_tokens"]
        assert isinstance(tokens, list)
        tokens.append(token)
        if token == "deny401":
            raise web.HTTPUnauthorized
        if token == "redirect":
            location = f"http://{request.headers['Host']}/api/webui/ws?token=followed"
            return web.Response(status=302, headers={"Location": location})
        cookies = state["ws_cookies"]
        headers = state["ws_headers"]
        assert isinstance(cookies, list)
        assert isinstance(headers, list)
        cookies.append(request.headers.get("Cookie", ""))
        headers.append(dict(request.headers))
        ws = web.WebSocketResponse(max_msg_size=proxy.MAX_WEBSOCKET_MESSAGE_BYTES)
        ws.set_cookie("maibot_session", "ws-native", path="/", httponly=True)
        await ws.prepare(request)

        async def stream_ticks() -> None:
            while not ws.closed:
                try:
                    await ws.send_str("tick")
                except (ConnectionResetError, RuntimeError):
                    return
                state["ws_ticks"] = int(state["ws_ticks"]) + 1
                await asyncio.sleep(0.01)

        ticks = asyncio.create_task(stream_ticks()) if token == "stream" else None
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    await ws.send_str(message.data)
                elif message.type == WSMsgType.BINARY:
                    await ws.send_bytes(message.data)
        finally:
            if ticks is not None:
                ticks.cancel()
                await asyncio.gather(ticks, return_exceptions=True)
        return ws

    async def run_server() -> tuple[web.AppRunner, int]:
        app = web.Application()
        app.router.add_get("/api/webui/ws", websocket)
        app.router.add_get("/ws/logs", websocket)
        app.router.add_route("*", "/{path:.*}", echo)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        assert site._server is not None
        port = site._server.sockets[0].getsockname()[1]
        return runner, port

    def serve() -> None:
        asyncio.set_event_loop(loop)
        try:
            runner, port = loop.run_until_complete(run_server())
            state["runner"] = runner
            state["port"] = port
            started.set()
            loop.run_forever()
            loop.run_until_complete(runner.cleanup())
        except BaseException as exc:  # surfaced in the fixture's owning thread
            thread_error.append(exc)
            started.set()

    thread = threading.Thread(target=serve, name="dashboard-proxy-native-fixture", daemon=True)
    thread.start()
    assert started.wait(5), "loopback MaiBot fixture failed to start"
    if thread_error:
        raise thread_error[0]
    try:
        yield state
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("loopback MaiBot fixture failed to stop")
        loop.close()
        if thread_error:
            raise thread_error[0]


@pytest.fixture
def proxy_app(loopback_native: dict[str, object]):
    app = FastAPI()
    target = {"value": ("127.0.0.1", loopback_native["port"])}
    process = {"pid": 4242}
    session = {"valid": True}
    proxy.register_dashboard_proxy(
        app,
        target_resolver=lambda: target["value"],
        process_provider=lambda: process["pid"],
        session_verifier=lambda token: session["valid"] and token == _SESSION,
    )

    @app.get("/{path:path}")
    async def pallas_catchall(path: str):
        return {"caught_by_pallas": path}

    return app, loopback_native, target, process, session


def _login(client: TestClient) -> None:
    client.cookies.set(_COOKIE, _SESSION, path="/")


def _same_origin() -> dict[str, str]:
    return {"Origin": "http://testserver"}


def test_unauthenticated_http_never_reaches_maibot(proxy_app):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        page = client.get("/pallas/maibot/deep/index.html", follow_redirects=False)
        assert page.status_code == 307
        assert page.headers["location"].startswith("/pallas/login?next=%2Fpallas%2Fmaibot%2F")
        assert client.get("/pallas/maibot/api/items").status_code == 401
        assert client.post("/pallas/maibot/api/items").status_code == 401
        assert (
            client.get(
                "/pallas/maibot/api/items?token=valid-pallas-session",
                headers={"X-Pallas-Api-Key": _SESSION, "Authorization": f"Bearer {_SESSION}"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/pallas/maibot/api/items",
                headers={"Cookie": f"pallas_webui_page_token={_SESSION}"},
            ).status_code
            == 401
        )
    assert requests == []


def test_proxy_root_redirects_only_authenticated_get_and_head(proxy_app):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        unauthenticated = client.get(proxy.PREFIX, follow_redirects=False)
        assert unauthenticated.status_code == 307
        assert unauthenticated.headers["location"].startswith("/pallas/login?next=")
        _login(client)
        root = client.get(f"{proxy.PREFIX}?view=config", headers=_same_origin(), follow_redirects=False)
        head = client.head(proxy.PREFIX, headers=_same_origin(), follow_redirects=False)
        assert root.status_code == 307
        assert root.headers["location"] == f"{proxy.PREFIX}/?view=config"
        assert head.status_code == 307
        posted = client.post(proxy.PREFIX, headers=_same_origin(), content=b"not redirected")
        assert posted.status_code == 200
    assert len(requests) == 1
    assert requests[0]["method"] == "POST"
    assert requests[0]["path"] == "/"


@pytest.mark.parametrize(
    "path",
    [
        "/pallas/maibot/%2fetc/passwd",
        "/pallas/maibot/%252e%252e/escape",
        "/pallas/maibot/api/items?token=legacy",
        "/pallas/maibot/api/items?%2570allas_console_session=secret",
    ],
)
def test_unsafe_paths_and_http_auth_query_parameters_are_rejected(proxy_app, path):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        _login(client)
        response = client.get(path, headers=_same_origin())
    assert response.status_code == 400
    assert requests == []


def test_stream_proxy_strips_prefix_and_pallas_credentials(proxy_app):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        _login(client)
        response = client.get(
            "/pallas/maibot/resource/data.bin?version=4",
            headers={
                **_same_origin(),
                "Cookie": f"{_COOKIE}={_SESSION}; {_NATIVE_COOKIE}=native-A; unrelated=ignored",
                "X-Pallas-Api-Key": "never-forward",
                "Authorization": "Bearer never-forward",
                "Range": "bytes=0-10",
                "Accept-Encoding": "identity",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.8",
                "X-Forwarded-Host": "attacker.invalid",
            },
        )
        assert response.status_code == 200
        assert response.headers["x-native-status"] == "passed"
        assert response.request.url.path == "/pallas/maibot/resource/data.bin"
    forwarded = requests[-1]
    assert forwarded["path"] == "/resource/data.bin"
    assert forwarded["query"] == "version=4"
    assert forwarded["headers"]["Cookie"] == "maibot_session=native-A"
    assert forwarded["headers"]["Range"] == "bytes=0-10"
    assert forwarded["headers"]["Accept-Encoding"] == "identity"
    assert forwarded["headers"]["X-Forwarded-Proto"] == "http"
    assert "X-Forwarded-For" not in forwarded["headers"]
    assert "X-Forwarded-Host" not in forwarded["headers"]
    assert "X-Pallas-Api-Key" not in forwarded["headers"]
    assert "Authorization" not in forwarded["headers"]
    assert _COOKIE not in forwarded["headers"]["Cookie"]


def test_csrf_requires_same_origin_and_referrer_fallback(proxy_app):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        _login(client)
        before = len(requests)
        denied = client.post("/pallas/maibot/api/items", headers={"Origin": "https://attacker.invalid"})
        assert denied.status_code == 403
        assert client.get("/pallas/maibot/home", headers={"Origin": "null"}).status_code == 403
        assert len(requests) == before
        accepted = client.post(
            "/pallas/maibot/api/items",
            headers={"Referer": "http://testserver/pallas/form", "Sec-Fetch-Site": "same-origin"},
            content=b"ok",
        )
        assert accepted.status_code == 200
        assert (
            client.post(
                "/pallas/maibot/api/items",
                headers={"Referer": "http://testserver/pallas/form", "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )


def test_native_response_status_redirect_compression_and_head_are_preserved(proxy_app):
    app, *_ = proxy_app
    with TestClient(app) as client:
        _login(client)
        assert client.get("/pallas/maibot/status401", headers=_same_origin()).status_code == 401
        redirect = client.get("/pallas/maibot/redirect-internal", headers=_same_origin(), follow_redirects=False)
        assert redirect.status_code == 302
        assert redirect.headers["location"] == "/pallas/maibot/ui/login?next=dashboard"
        denied = client.get("/pallas/maibot/redirect-external", headers=_same_origin(), follow_redirects=False)
        assert denied.status_code == 502
        compressed = client.get("/pallas/maibot/compressed", headers={**_same_origin(), "Accept-Encoding": "gzip"})
        assert compressed.headers["content-encoding"] == "gzip"
        assert compressed.content == b"native compressed response"
        head = client.head("/pallas/maibot/head", headers=_same_origin())
        assert head.status_code == 200
        assert head.content == b""


@pytest.mark.parametrize("asset", ["app.ico", "app.js", "app.css", "app.map", "font.woff2", "font.woff", "font.ttf"])
def test_static_assets_do_not_receive_spa_html_fallback(proxy_app, asset):
    app, *_ = proxy_app
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/pallas/maibot/assets/{asset}", headers=_same_origin())
    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}


@pytest.mark.parametrize("path", ["/assets/missing.png", "/fonts/missing.txt"])
def test_static_directories_never_fallback_even_for_other_file_types(proxy_app, path):
    app, *_ = proxy_app
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/pallas/maibot{path}", headers=_same_origin())
    assert response.status_code == 404


def test_api_fallback_is_rejected_but_deep_html_and_native_statistics_status_survive(proxy_app):
    app, *_ = proxy_app
    with TestClient(app) as client:
        _login(client)
        api = client.get("/pallas/maibot/api/not-real", headers=_same_origin())
        deep_page = client.get("/pallas/maibot/config/model", headers=_same_origin())
        statistics = client.get("/pallas/maibot/maibot_statistics.html", headers=_same_origin())
    assert api.status_code == 502
    assert deep_page.status_code == 200
    assert deep_page.text == "<html>spa shell</html>"
    assert statistics.status_code == 404
    assert statistics.text == "native statistics route not found"


def test_browser_response_cannot_clear_pallas_cookies_change_service_worker_scope_or_refresh(proxy_app):
    app, *_ = proxy_app
    with TestClient(app) as client:
        _login(client)
        response = client.get("/pallas/maibot/sensitive-headers", headers=_same_origin())
    assert response.status_code == 200
    assert "clear-site-data" not in response.headers
    assert "service-worker-allowed" not in response.headers
    assert "refresh" not in response.headers
    assert response.headers["etag"] == '"native-v1"'


def test_native_cookie_is_remapped_scoped_and_isolated(proxy_app):
    app, native, *_ = proxy_app
    ws_cookies = native["ws_cookies"]
    assert isinstance(ws_cookies, list)
    with TestClient(app) as client:
        _login(client)
        response = client.get(
            "/pallas/maibot/cookies",
            headers={**_same_origin(), "Cookie": f"{_COOKIE}={_SESSION}; {_NATIVE_COOKIE}=native-A"},
        )
        set_cookies = response.headers.get_list("set-cookie")
        assert len(set_cookies) == 1
        assert set_cookies[0].startswith(f"{_NATIVE_COOKIE}=native-one; Path=/pallas/maibot/; HttpOnly; SameSite=Lax")
        assert "Domain=" not in set_cookies[0]
        assert "pallas_console_session" not in set_cookies[0]
        deleted = client.get("/pallas/maibot/delete-cookie", headers=_same_origin())
        assert "Max-Age=0" in deleted.headers["set-cookie"]
        client.get(
            "/pallas/maibot/api/items",
            headers={**_same_origin(), "Cookie": f"{_COOKIE}={_SESSION}; {_NATIVE_COOKIE}=native-B"},
        )
    requests = native["requests"]
    assert isinstance(requests, list)
    assert requests[-1]["headers"]["Cookie"] == "maibot_session=native-B"


def test_native_cookie_is_secure_when_browser_is_https(proxy_app):
    app, native, *_ = proxy_app
    with TestClient(app, base_url="https://testserver") as client:
        _login(client)
        response = client.get(
            "/pallas/maibot/cookies",
            headers={
                "Origin": "https://testserver",
                "Cookie": f"{_COOKIE}={_SESSION}",
                "X-Forwarded-Proto": "http",
            },
        )
    assert "Secure" in response.headers["set-cookie"]
    requests = native["requests"]
    assert isinstance(requests, list)
    assert requests[-1]["headers"]["X-Forwarded-Proto"] == "https"


@pytest.mark.parametrize(
    "cookie",
    [
        f"{_COOKIE}={_SESSION}; {_COOKIE}={_SESSION}",
        f"{_COOKIE}={_SESSION}; {_NATIVE_COOKIE}=a; {_NATIVE_COOKIE}=b",
    ],
)
def test_duplicate_auth_or_native_cookie_fails_closed(proxy_app, cookie):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        response = client.get("/pallas/maibot/api/items", headers={**_same_origin(), "Cookie": cookie})
    assert response.status_code == 400
    assert requests == []


def test_websocket_requires_both_auth_layers_and_preserves_native_token(proxy_app):
    app, native, *_ = proxy_app
    ws_tokens = native["ws_tokens"]
    ws_cookies = native["ws_cookies"]
    ws_headers = native["ws_headers"]
    assert isinstance(ws_tokens, list)
    assert isinstance(ws_cookies, list)
    assert isinstance(ws_headers, list)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(
                "/pallas/maibot/api/webui/ws?token=native-temp",
                headers={"Origin": "http://testserver"},
            ):
                pass
        assert denied.value.status_code == 403
        assert ws_tokens == []
        _login(client)
        with client.websocket_connect(
            "/pallas/maibot/api/webui/ws?token=native-temp",
            headers={
                "Origin": "http://testserver",
                "Cookie": f"{_COOKIE}={_SESSION}; {_NATIVE_COOKIE}=native-ws",
                "X-Pallas-Api-Key": "never-forward",
                "Authorization": "Bearer never-forward",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.8",
            },
        ) as websocket:
            websocket.send_text("ping")
            assert websocket.receive_text() == "ping"
    assert ws_tokens == ["native-temp"]
    assert ws_cookies == ["maibot_session=native-ws"]
    assert "X-Pallas-Api-Key" not in ws_headers[0]
    assert "Authorization" not in ws_headers[0]
    assert ws_headers[0]["Origin"] == f"http://127.0.0.1:{native['port']}"
    assert ws_headers[0]["X-Forwarded-Proto"] == "http"
    assert "X-Forwarded-For" not in ws_headers[0]


def test_websocket_denies_cross_origin_native_401_and_redirect(proxy_app):
    app, native, *_ = proxy_app
    ws_tokens = native["ws_tokens"]
    assert isinstance(ws_tokens, list)
    with TestClient(app) as client:
        _login(client)
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect("/pallas/maibot/api/webui/ws?token=native-temp", headers={"Origin": "null"}):
                pass
        assert denied.value.status_code == 403
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(
                "/pallas/maibot/api/webui/ws?token=deny401", headers={"Origin": "http://testserver"}
            ):
                pass
        assert denied.value.status_code == 401
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(
                "/pallas/maibot/api/webui/ws?token=redirect", headers={"Origin": "http://testserver"}
            ):
                pass
        assert denied.value.status_code == 502
    assert ws_tokens == ["deny401", "redirect"]


@pytest.mark.parametrize("changed", ["session", "process", "target"])
def test_websocket_revalidates_identity_after_upstream_handshake(proxy_app, changed):
    app, native, target, process, _session = proxy_app
    state = app.state.maibot_dashboard_proxy
    calls = 0
    if changed == "session":

        def verify_session(token):
            nonlocal calls
            calls += 1
            return calls == 1 and token == _SESSION

        state.session_verifier = verify_session
        expected_status = 403
    elif changed == "process":

        def process_id():
            nonlocal calls
            calls += 1
            return process["pid"] if calls == 1 else process["pid"] + 1

        state.process_provider = process_id
        expected_status = 503
    else:

        def resolve_target():
            nonlocal calls
            calls += 1
            host, port = target["value"]
            return (host, port) if calls == 1 else (host, port + 1)

        state.target_resolver = resolve_target
        expected_status = 503

    with TestClient(app) as client:
        _login(client)
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(
                "/pallas/maibot/ws/logs?token=handshake",
                headers={"Origin": "http://testserver"},
            ):
                pass
    assert denied.value.status_code == expected_status
    assert native["ws_tokens"] == ["handshake"]


def test_websocket_closes_when_session_rotates_or_managed_process_changes(proxy_app, monkeypatch):
    app, _native, _target, process, session = proxy_app
    monkeypatch.setattr(proxy, "WS_REAUTH_INTERVAL_SEC", 0.05)
    with TestClient(app) as client:
        _login(client)
        with client.websocket_connect("/pallas/maibot/ws/logs", headers={"Origin": "http://testserver"}) as websocket:
            session["valid"] = False
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_text()
        session["valid"] = True
        with client.websocket_connect("/pallas/maibot/ws/logs", headers={"Origin": "http://testserver"}) as websocket:
            process["pid"] = 4243
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_text()


def test_websocket_reauth_deadline_is_enforced_during_continuous_native_traffic(proxy_app, monkeypatch):
    app, native, _target, _process, session = proxy_app
    monkeypatch.setattr(proxy, "WS_REAUTH_INTERVAL_SEC", 0.1)
    with TestClient(app) as client:
        _login(client)
        with client.websocket_connect(
            "/pallas/maibot/ws/logs?token=stream",
            headers={"Origin": "http://testserver", "Cookie": f"{_COOKIE}={_SESSION}"},
        ) as websocket:
            for _ in range(3):
                assert websocket.receive_text() == "tick"
            tick_count = int(native["ws_ticks"])
            session["valid"] = False
            invalidated_at = time.monotonic()
            close_code = None
            for _ in range(60):
                try:
                    assert websocket.receive_text() == "tick"
                except WebSocketDisconnect as exc:
                    close_code = exc.code
                    break
            else:
                pytest.fail("WebSocket remained open past its session revalidation deadline")
            assert close_code == 1008
            assert time.monotonic() - invalidated_at < 0.4
            assert int(native["ws_ticks"]) - tick_count >= 3


def test_invalid_target_and_unowned_process_return_503_without_upstream(proxy_app):
    app, native, target, process, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    with TestClient(app) as client:
        _login(client)
        target["value"] = ("localhost", 8001)
        assert client.get("/pallas/maibot/home", headers=_same_origin()).status_code == 503
        target["value"] = ("127.0.0.1", native["port"])
        process["pid"] = None
        assert client.get("/pallas/maibot/home", headers=_same_origin()).status_code == 503
    assert requests == []


def test_body_limit_checks_content_length_and_chunked_stream(proxy_app, monkeypatch):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)
    monkeypatch.setattr(proxy, "MAX_REQUEST_BODY_BYTES", 10)
    with TestClient(app) as client:
        _login(client)
        assert client.post("/pallas/maibot/upload", headers=_same_origin(), content=b"x" * 11).status_code == 413
        response = client.post(
            "/pallas/maibot/upload",
            headers=_same_origin(),
            content=iter([b"123456", b"789012"]),
        )
        assert response.status_code == 413
    uploaded = [row["body"] for row in requests if row["path"] == "/upload"]
    assert all(len(body) <= 10 for body in uploaded)


def test_asgi_content_length_digit_limit_is_bounded_and_auth_remains_first(proxy_app):
    app, native, *_ = proxy_app
    requests = native["requests"]
    assert isinstance(requests, list)

    async def run_cases():
        async def request(raw_length: bytes, *, authenticated: bool):
            received = 0
            messages = []

            async def receive():
                nonlocal received
                received += 1
                return {"type": "http.request", "body": b"x", "more_body": False}

            async def send(message):
                messages.append(message)

            headers = [
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"content-length", raw_length),
            ]
            if authenticated:
                headers.append((b"cookie", f"{_COOKIE}={_SESSION}".encode()))
            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/pallas/maibot/upload",
                "raw_path": b"/pallas/maibot/upload",
                "query_string": b"",
                "root_path": "",
                "headers": headers,
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 12345),
                "state": {},
            }
            await app(scope, receive, send)
            status = next(message["status"] for message in messages if message["type"] == "http.response.start")
            return status, received

        return (
            await request(b"9" * 5000, authenticated=True),
            await request(b"-1", authenticated=True),
            await request("١".encode(), authenticated=True),
            await request(b"9" * 5000, authenticated=False),
        )

    assert asyncio.run(run_cases()) == ((413, 0), (400, 0), (400, 0), (401, 0))
    assert requests == []


@pytest.mark.parametrize("target", [("localhost", 8001), ("0.0.0.0", 8001), ("8.8.8.8", 8001), ("127.0.0.1", 0)])
def test_target_validator_only_accepts_fixed_loopback(target):
    assert proxy._validate_target(target) is None


def test_managed_native_webui_config_is_read_only_and_restricted(tmp_path, monkeypatch):
    instance = tmp_path / "instance"
    config_dir = instance / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "bot_config.toml"
    managed = SimpleNamespace(enabled=True, instance_dir=instance)
    from pallas.console.cli import maibot_aux

    monkeypatch.setattr(maibot_aux, "load_managed_config", lambda: managed)
    config_path.write_text('[webui]\nenabled = true\nhost = ["127.0.0.1", "::1"]\nport = 8123\n')
    assert proxy._configured_target() == ("127.0.0.1", 8123)
    config_path.write_text('[webui]\nenabled = true\nhost = "localhost"\nport = 8123\n')
    assert proxy._configured_target() is None
    config_path.write_text("[webui]\nenabled = false\n")
    assert proxy._configured_target() is None


def test_proxy_route_precedes_later_catchall_and_repeated_registration_is_idempotent(proxy_app):
    app, native, *_ = proxy_app
    matches = [route.path for route in app.router.routes if getattr(route, "path", "") == proxy.PREFIX]
    assert len(matches) == 1
    catchall_index = next(
        index for index, route in enumerate(app.router.routes) if getattr(route, "path", "") == "/{path:path}"
    )
    proxy_index = next(
        index for index, route in enumerate(app.router.routes) if getattr(route, "path", "") == proxy.PREFIX
    )
    assert proxy_index < catchall_index
    assert proxy.register_dashboard_proxy(app) is app.state.maibot_dashboard_proxy
    with TestClient(app) as client:
        _login(client)
        response = client.get("/pallas/maibot/deep/refresh", headers=_same_origin())
    assert response.status_code == 200
    assert response.content == b""


def test_downstream_disconnect_closes_the_native_response_stream(proxy_app):
    app, native, *_ = proxy_app
    disconnect_seen = native.setdefault("disconnect_seen", threading.Event())
    assert isinstance(disconnect_seen, threading.Event)
    started = threading.Event()

    async def run_request() -> None:
        received_request = False

        async def receive():
            nonlocal received_request
            if not received_request:
                received_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Future()

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                started.set()
                raise OSError("synthetic browser disconnect")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/pallas/maibot/slow",
            "raw_path": b"/pallas/maibot/slow",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"cookie", f"{_COOKIE}={_SESSION}".encode()),
            ],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "state": {},
        }
        try:
            await app(scope, receive, send)
        except OSError:
            pass
        finally:
            await app.state.maibot_dashboard_proxy.close()

    asyncio.run(run_request())
    assert started.is_set()
    assert disconnect_seen.wait(2)
