from __future__ import annotations

import asyncio
import gzip
import json
import sys
import threading
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from pallas.product.arknights_mcp.auth import CredentialStore
from pallas.product.arknights_mcp.server import create_app, run_sync_query

if TYPE_CHECKING:
    from pathlib import Path

TEST_SPECS = {
    "arknights.operator.get": {
        "description": "Look up an operator.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 80}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "scope": "arknights:read",
    },
    "arknights.skill.get": {
        "description": "Look up a skill.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "skill_index": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": ["name", "skill_index"],
            "additionalProperties": False,
        },
        "scope": "arknights:read",
    },
    "prts.search": {
        "description": "Search the local PRTS corpus.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "scope": "prts:read",
    },
}


def make_app(tmp_path: Path, *, executor=None, **kwargs):
    return create_app(
        data_root=tmp_path,
        specs=TEST_SPECS,
        executor=executor or (lambda name, arguments: {"ok": True, "error": "", "result": {"tool": name, **arguments}}),
        allowed_hosts=("127.0.0.1:8765",),
        **kwargs,
    )


@asynccontextmanager
async def connected_client(app, secret: str, *, extra_headers=None, mode="legacy"):
    async with httpx2.AsyncClient(
        base_url="http://127.0.0.1:8765",
        transport=httpx2.ASGITransport(app=app),
        headers={"Authorization": f"Bearer {secret}", **(extra_headers or {})},
    ) as http_client:
        transport = streamable_http_client(
            "http://127.0.0.1:8765/mcp",
            http_client=http_client,
            terminate_on_close=False,
        )
        options = {} if mode is None else {"mode": mode}
        async with Client(transport, **options) as client:
            yield client


@pytest.mark.asyncio
async def test_official_client_initialize_list_call_and_scope_filter(tmp_path: Path):
    app = make_app(tmp_path)
    store = CredentialStore(tmp_path)
    full_key, _ = store.issue()
    arknights_key, _ = store.issue(scopes={"arknights:read"})

    async with app.router.lifespan_context(app):
        async with connected_client(app, full_key) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == set(TEST_SPECS)
            operator = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
            assert operator.structured_content == {
                "ok": True,
                "error": "",
                "result": {"tool": "arknights.operator.get", "name": "Amiya"},
            }

        async with connected_client(app, arknights_key) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {"arknights.operator.get", "arknights.skill.get"}
            rejected = await client.call_tool("prts.search", {"query": "Originium"})
            assert rejected.is_error

        assert app.state.key_store.revoke(store.list()[0]["id"])
        async with httpx2.AsyncClient(
            base_url="http://127.0.0.1:8765",
            transport=httpx2.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {full_key}"},
        ) as http_client:
            response = await http_client.get("/mcp")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_default_client_mode_scopes_calls_and_observes_revocation(tmp_path: Path):
    app = make_app(tmp_path)
    store = CredentialStore(tmp_path)
    full_key, full_id = store.issue()
    arknights_key, _ = store.issue(scopes={"arknights:read"})

    async with app.router.lifespan_context(app):
        async with connected_client(app, full_key, mode=None) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == set(TEST_SPECS)
            result = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
            assert result.structured_content["ok"] is True

            assert app.state.key_store.revoke(full_id)
            with pytest.raises(MCPError):
                await client.list_tools()

        async with connected_client(app, arknights_key, mode=None) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {"arknights.operator.get", "arknights.skill.get"}
            rejected = await client.call_tool("prts.search", {"query": "Originium"})
            assert rejected.is_error


@pytest.mark.asyncio
async def test_default_app_uses_shared_service_schema_and_query_result(tmp_path: Path, monkeypatch):
    from pallas.product.arknights_kb import prts_runtime, service
    from pallas.product.arknights_kb.config import ArknightsKbConfig
    from pallas.product.arknights_kb.prts_corpus import CorpusStore

    monkeypatch.setattr(service, "get_arknights_kb_config", lambda: ArknightsKbConfig())
    monkeypatch.setattr(
        service.ark_query,
        "load_kb_operators_payload",
        lambda: {
            "source": "synthetic-operators",
            "rarity_filter": "ALL",
            "operators": [
                {
                    "id": "char_amiya",
                    "name": "阿米娅",
                    "rarity": 5,
                    "profession_cn": "术师",
                    "skills": [{"name": "精神爆发", "description": "合成技能描述"}],
                }
            ],
        },
    )
    monkeypatch.setattr(
        service.ark_query,
        "load_enemies_payload",
        lambda: {
            "source": "synthetic-enemies",
            "enemies": [{"id": "enemy_1", "name": "源石虫", "description": "合成敌人", "abilities": []}],
        },
    )

    corpus_data = tmp_path / "synthetic-corpus"
    release_dir = corpus_data / "releases" / "fixture-r1" / "references"
    document = {
        "document_id": "fixture:references:timeline",
        "display_title": "凛冬年表",
        "document_type": "reference",
        "document_kind": "reference",
        "source_ref_prefix": "fixture:references:timeline",
    }
    record = {
        "document": document,
        "lines": [
            {"line_number": 1, "speaker_raw": "凛冬", "text": "凛冬参加测试年表。"},
            {"line_number": 2, "speaker_raw": "", "text": "/...合成年表记录。"},
        ],
    }
    catalog_row = {"document": document, "shard_path": "shards/00000.jsonl.gz", "record_index": 0}
    shard_path = release_dir / "shards/00000.jsonl.gz"
    catalog_path = release_dir / "catalog/documents.jsonl.gz"
    shard_path.parent.mkdir(parents=True)
    catalog_path.parent.mkdir(parents=True)
    shard_path.write_bytes(gzip.compress((json.dumps(record, ensure_ascii=False) + "\n").encode()))
    catalog_path.write_bytes(gzip.compress((json.dumps(catalog_row, ensure_ascii=False) + "\n").encode()))
    (release_dir / "pack-manifest.json").write_text(
        json.dumps({"pack_id": "references", "document_catalog": {"path": "catalog/documents.jsonl.gz"}}),
        encoding="utf-8",
    )
    (corpus_data / "releases/current.json").write_text(
        json.dumps({"release_id": "fixture-r1", "data_version": "a" * 64, "packs": ["references"]}),
        encoding="utf-8",
    )
    store = CorpusStore(corpus_data)
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: store)

    arguments = {
        "arknights.operator.get": {"name": "阿米娅"},
        "arknights.operator.search": {"query": "阿米娅"},
        "arknights.skill.get": {"name": "阿米娅", "skill_index": 1},
        "arknights.enemy.get": {"name": "源石虫"},
        "arknights.enemy.search": {"query": "源石虫"},
        "prts.search": {"query": "凛冬"},
        "prts.read": {"document_id": "fixture:references:timeline"},
        "prts.timeline": {"query": "年表"},
    }
    expected = {name: service.execute_query(name, args) for name, args in arguments.items()}
    app = create_app(data_root=tmp_path, allowed_hosts=("127.0.0.1:8765",))
    secret, _ = CredentialStore(tmp_path).issue()

    async with app.router.lifespan_context(app), connected_client(app, secret) as client:
        listed = await client.list_tools()
        schemas = {tool.name: tool.input_schema for tool in listed.tools}
        assert set(schemas) == set(service.QUERY_TOOLS)
        assert schemas == {name: spec["parameters"] for name, spec in service.QUERY_TOOLS.items()}
        for tool in listed.tools:
            assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            }
            assert tool.output_schema == {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "error": {"type": "string"},
                    "result": {"anyOf": [{"type": "object"}, {"type": "null"}]},
                },
                "required": ["ok", "error", "result"],
                "additionalProperties": False,
            }
        actual = {name: (await client.call_tool(name, args)).structured_content for name, args in arguments.items()}
        whitespace = await client.call_tool("arknights.operator.get", {"name": "   "})

    assert actual == expected
    assert all(result["ok"] for result in actual.values())
    assert actual["arknights.operator.get"]["result"]["found"]
    assert actual["arknights.skill.get"]["result"]["found"]
    assert actual["arknights.enemy.get"]["result"]["found"]
    assert actual["prts.read"]["result"]["found"]
    assert actual["prts.read"]["result"]["lines"][1]["text"] == "/...合成年表记录。"
    assert whitespace.structured_content == {"ok": False, "error": "invalid_arguments", "result": None}


@pytest.mark.asyncio
async def test_auth_duplicate_headers_url_token_host_origin_and_body_limits(tmp_path: Path):
    app = make_app(tmp_path, max_request_body_size=1024)
    secret, _ = CredentialStore(tmp_path).issue()
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(base_url="http://127.0.0.1:8765", transport=transport) as client,
    ):
        for headers in (
            {},
            {"Authorization": "Bearer pls_not_a_mcp_key"},
            {"Authorization": "Bearer pmcp_invalid"},
        ):
            response = await client.get("/mcp", headers=headers)
            assert response.status_code == 401
            assert response.headers["www-authenticate"].startswith("Bearer")

        duplicate = await client.get(
            "/mcp",
            headers=[("Authorization", f"Bearer {secret}"), ("Authorization", f"Bearer {secret}")],
        )
        assert duplicate.status_code == 401

        denied_delete = await client.delete("/mcp")
        assert denied_delete.status_code == 401

        missing_url_key = await client.get("/mcp?access_token=not-accepted")
        assert missing_url_key.status_code == 401
        assert missing_url_key.headers["www-authenticate"].startswith("Bearer")

        url_key = await client.get(
            "/mcp?access_token=not-accepted",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert url_key.status_code == 400

        bad_host = await client.get("/mcp", headers={"Authorization": f"Bearer {secret}", "Host": "evil.example"})
        assert bad_host.status_code == 421

        bad_origin = await client.get(
            "/mcp",
            headers={"Authorization": f"Bearer {secret}", "Origin": "https://evil.example"},
        )
        assert bad_origin.status_code == 403

        too_large = await client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            content=b"x" * 2048,
        )
        assert too_large.status_code == 413


def test_host_and_origin_configuration_is_exact_and_remote_is_opt_in():
    with pytest.raises(ValueError, match="allow-remote"):
        create_app(specs=TEST_SPECS, executor=lambda *_: {}, host="0.0.0.0")
    with pytest.raises(ValueError, match="explicit allowed hosts"):
        create_app(specs=TEST_SPECS, executor=lambda *_: {}, host="0.0.0.0", allow_remote=True)
    with pytest.raises(ValueError, match="exact Host"):
        create_app(
            specs=TEST_SPECS,
            executor=lambda *_: {},
            allowed_hosts=("*",),
        )
    with pytest.raises(ValueError, match=r"exact HTTP\(S\) origins"):
        create_app(
            specs=TEST_SPECS,
            executor=lambda *_: {},
            allowed_hosts=("127.0.0.1:8765",),
            allowed_origins=("https://*.example",),
        )


@pytest.mark.asyncio
async def test_unknown_and_extra_arguments_never_reach_executor(tmp_path: Path):
    calls = []
    app = make_app(
        tmp_path,
        executor=lambda name, args: calls.append((name, args)) or {"ok": True, "error": "", "result": {}},
    )
    secret, _ = CredentialStore(tmp_path).issue()
    async with app.router.lifespan_context(app):
        async with connected_client(app, secret) as client:
            extra = await client.call_tool("arknights.operator.get", {"name": "Amiya", "admin": True})
            bool_integer = await client.call_tool("arknights.skill.get", {"name": "Amiya", "skill_index": True})
            unknown = await client.call_tool("admin.update", {})

    assert extra.is_error
    assert bool_integer.is_error
    assert unknown.is_error
    assert calls == []


@pytest.mark.asyncio
async def test_output_size_and_exception_details_are_not_returned(tmp_path: Path):
    app = make_app(
        tmp_path,
        executor=lambda *_: {"ok": True, "error": "", "result": {"text": "x" * (64 * 1024)}},
    )
    secret, _ = CredentialStore(tmp_path).issue()
    async with app.router.lifespan_context(app), connected_client(app, secret) as client:
        too_large = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
        assert too_large.structured_content == {"ok": False, "error": "output_limit_exceeded", "result": None}

    broken = make_app(tmp_path / "broken", executor=lambda *_: (_ for _ in ()).throw(RuntimeError("/private/path")))
    broken_key, _ = CredentialStore(tmp_path / "broken").issue()
    async with broken.router.lifespan_context(broken), connected_client(broken, broken_key) as client:
        result = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
    assert result.structured_content == {"ok": False, "error": "query_failed", "result": None}

    paths = make_app(
        tmp_path / "paths",
        executor=lambda *_: {"ok": True, "error": "", "result": {"source_path": "/private/data/source.json"}},
    )
    path_key, _ = CredentialStore(tmp_path / "paths").issue()
    async with paths.router.lifespan_context(paths), connected_client(paths, path_key) as client:
        result = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
    assert result.structured_content == {"ok": False, "error": "query_failed", "result": None}
    assert "/private/data/source.json" not in repr(result)

    private_error = make_app(
        tmp_path / "private-error",
        executor=lambda *_: {"ok": True, "error": "", "result": {"error": "privatepath /srv/private"}},
    )
    private_error_key, _ = CredentialStore(tmp_path / "private-error").issue()
    async with (
        private_error.router.lifespan_context(private_error),
        connected_client(private_error, private_error_key) as client,
    ):
        result = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
    assert result.structured_content == {"ok": False, "error": "query_failed", "result": None}
    assert "privatepath" not in repr(result)

    safe = make_app(
        tmp_path / "safe",
        executor=lambda *_: {
            "ok": True,
            "error": "",
            "result": {"pathology": "business metadata", "description": "/...quoted source text"},
        },
    )
    safe_key, _ = CredentialStore(tmp_path / "safe").issue()
    async with safe.router.lifespan_context(safe), connected_client(safe, safe_key) as client:
        result = await client.call_tool("arknights.operator.get", {"name": "Amiya"})
    assert result.structured_content == {
        "ok": True,
        "error": "",
        "result": {"pathology": "business metadata", "description": "/...quoted source text"},
    }


@pytest.mark.asyncio
async def test_rate_limits_are_independent_per_verified_key(tmp_path: Path):
    app = make_app(tmp_path, rate_limit=1, rate_window_seconds=3600)
    first, _ = CredentialStore(tmp_path).issue()
    second, _ = CredentialStore(tmp_path).issue()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(base_url="http://127.0.0.1:8765", transport=httpx2.ASGITransport(app=app)) as client,
    ):
        first_headers = {"Authorization": f"Bearer {first}"}
        second_headers = {"Authorization": f"Bearer {second}"}
        assert (await client.head("/mcp", headers=first_headers)).status_code != 429
        limited = await client.head("/mcp", headers=first_headers)
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
        assert (await client.head("/mcp", headers=second_headers)).status_code != 429


@pytest.mark.asyncio
async def test_global_concurrency_rejects_excess_requests_and_exact_origin_passes(tmp_path: Path):
    app = make_app(
        tmp_path,
        concurrency=1,
        allowed_origins=("https://client.example",),
    )
    secret, _ = CredentialStore(tmp_path).issue()
    assert app.state.request_gate.enter()
    try:
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(base_url="http://127.0.0.1:8765", transport=httpx2.ASGITransport(app=app)) as client,
        ):
            busy = await client.head("/mcp", headers={"Authorization": f"Bearer {secret}"})
            assert busy.status_code == 429
            app.state.request_gate.leave()
            allowed = await client.head(
                "/mcp",
                headers={"Authorization": f"Bearer {secret}", "Origin": "https://client.example"},
            )
            assert allowed.status_code != 403
    finally:
        if app.state.request_gate.active:
            app.state.request_gate.leave()


@pytest.mark.asyncio
async def test_request_admission_limits_authentication_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = make_app(tmp_path, concurrency=1)
    valid_key, _ = CredentialStore(tmp_path).issue()
    invalid_key = f"pmcp_{'A' * 43}"
    auth_started = threading.Event()
    release_auth = threading.Event()
    auth_calls = 0
    authenticate = app.state.key_store.authenticate

    def blocked_authenticate(secret: str):
        nonlocal auth_calls
        auth_calls += 1
        if auth_calls == 1:
            auth_started.set()
            release_auth.wait(timeout=3)
        return authenticate(secret)

    monkeypatch.setattr(app.state.key_store, "authenticate", blocked_authenticate)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(base_url="http://127.0.0.1:8765", transport=httpx2.ASGITransport(app=app)) as client,
    ):
        first = asyncio.create_task(client.head("/mcp", headers={"Authorization": f"Bearer {invalid_key}"}))
        try:
            assert await anyio.to_thread.run_sync(lambda: auth_started.wait(timeout=3))
            overloaded = await client.head("/mcp", headers={"Authorization": f"Bearer {invalid_key}"})
            assert overloaded.status_code == 429
            assert auth_calls == 1
        finally:
            release_auth.set()

        assert (await first).status_code == 401
        assert app.state.request_gate.active == 0
        assert app.state.rate_limiter.entries == {}
        accepted = await client.head("/mcp", headers={"Authorization": f"Bearer {valid_key}"})
        assert accepted.status_code != 429
        assert auth_calls == 2


@pytest.mark.asyncio
async def test_cancelled_request_releases_global_admission_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pallas.product.arknights_mcp import server

    app = make_app(tmp_path, concurrency=1)
    secret, _ = CredentialStore(tmp_path).issue()
    origin_check_started = anyio.Event()

    async def wait_for_cancel(_self, _scope, _send):
        origin_check_started.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(server._McpRequestGuard, "_valid_host_origin", wait_for_cancel)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(base_url="http://127.0.0.1:8765", transport=httpx2.ASGITransport(app=app)) as client,
    ):
        request = asyncio.create_task(client.head("/mcp", headers={"Authorization": f"Bearer {secret}"}))
        await origin_check_started.wait()
        assert app.state.request_gate.active == 1
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert app.state.request_gate.active == 0


@pytest.mark.asyncio
async def test_cancelled_call_keeps_worker_capacity_until_sync_query_finishes():
    limiter = anyio.CapacityLimiter(1)
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    first_cancel_scope = None

    def first_query(_name, _args):
        started.set()
        release.wait(timeout=3)
        return {"ok": True, "error": "", "result": {}}

    def second_query(_name, _args):
        second_started.set()
        return {"ok": True, "error": "", "result": {}}

    async def run_first():
        nonlocal first_cancel_scope
        with anyio.CancelScope() as cancel_scope:
            first_cancel_scope = cancel_scope
            await run_sync_query(first_query, "first", {}, limiter)

    async def wait_for(event: threading.Event):
        await anyio.to_thread.run_sync(event.wait)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(run_first)
        await wait_for(started)
        assert first_cancel_scope is not None
        first_cancel_scope.cancel()
        tasks.start_soon(run_sync_query, second_query, "second", {}, limiter)
        await anyio.sleep(0.05)
        assert not second_started.is_set()
        release.set()
        await wait_for(second_started)
        tasks.cancel_scope.cancel()


def test_app_import_and_query_do_not_initialize_nonebot_in_subprocess(tmp_path: Path):
    import subprocess

    script = """
import asyncio
import sys
from pathlib import Path
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
import nonebot

def assert_nonebot_not_initialized():
    try:
        nonebot.get_driver()
    except ValueError as exc:
        assert 'not been initialized' in str(exc)
    else:
        raise AssertionError('NoneBot unexpectedly initialized')

assert_nonebot_not_initialized()
from pallas.product.arknights_kb import service
from pallas.product.arknights_kb.config import ArknightsKbConfig
from pallas.product.arknights_mcp.auth import CredentialStore
from pallas.product.arknights_mcp.server import create_app

assert_nonebot_not_initialized()
service.get_arknights_kb_config = ArknightsKbConfig
service._ark_query = lambda name, args: {'found': True, 'name': args['name'], 'operator': {'name': '阿米娅'}}

app = create_app(
    data_root=Path(sys.argv[1]),
    allowed_hosts=('127.0.0.1:8765',),
)
secret, _ = CredentialStore(Path(sys.argv[1])).issue()

async def run():
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        base_url='http://127.0.0.1:8765',
        transport=httpx2.ASGITransport(app=app),
        headers={'Authorization': f'Bearer {secret}'},
    ) as http:
        transport = streamable_http_client(
            'http://127.0.0.1:8765/mcp',
            http_client=http,
            terminate_on_close=False,
        )
        async with Client(transport, mode='legacy') as client:
                result = await client.call_tool('arknights.operator.get', {'name': '阿米娅'})
                assert result.structured_content['result']['operator']['name'] == '阿米娅'
                assert_nonebot_not_initialized()

asyncio.run(run())
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
