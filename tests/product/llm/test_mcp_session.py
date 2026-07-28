"""MCP 常驻 session 复用。"""

from __future__ import annotations

from pallas.product.llm.config import LlmMcpServerConfig
from pallas.product.llm.tools import mcp_bootstrap


class _FakeStdioSession(mcp_bootstrap._StdioMcpSession):
    def __init__(self, server_id: str, fingerprint: str) -> None:
        super().__init__(server_id=server_id, transport="stdio", fingerprint=fingerprint)
        self.starts = 0
        self.methods: list[str] = []

    def alive(self) -> bool:
        return True

    def ensure_started(self, server: LlmMcpServerConfig) -> None:
        self.starts += 1
        self.fingerprint = mcp_bootstrap._server_fingerprint(server)

    def call(self, *, method: str, params: dict | None = None) -> dict:
        self.methods.append(method)
        self.call_count += 1
        if method == "tools/list":
            return {"tools": [{"name": "ping", "description": "p", "inputSchema": {"type": "object"}}]}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "ok"}], "isError": False}
        return {}

    def close(self) -> None:
        return


def test_stdio_session_reused_across_calls(monkeypatch) -> None:
    mcp_bootstrap.close_all_mcp_sessions()
    created: list[_FakeStdioSession] = []

    def fake_new(server: LlmMcpServerConfig):
        session = _FakeStdioSession(server.id, mcp_bootstrap._server_fingerprint(server))
        session.ensure_started(server)
        created.append(session)
        return session

    monkeypatch.setattr(mcp_bootstrap, "_new_session", fake_new)
    server = LlmMcpServerConfig(id="demo", transport="stdio", command=["fake-mcp"])

    tools1 = mcp_bootstrap.list_mcp_tools(server)
    tools2 = mcp_bootstrap.list_mcp_tools(server)
    call = mcp_bootstrap.call_mcp_tool(server, tool_name="ping", arguments={})

    assert tools1[0]["name"] == "ping"
    assert tools2[0]["name"] == "ping"
    assert call["is_error"] is False
    assert len(created) == 1
    assert created[0].call_count == 3
    assert created[0].methods == ["tools/list", "tools/list", "tools/call"]
    snap = mcp_bootstrap.mcp_registration_snapshot()
    assert snap["sessions"][0]["id"] == "demo"
    assert snap["sessions"][0]["alive"] is True
    mcp_bootstrap.close_all_mcp_sessions()


def test_session_recreated_when_fingerprint_changes(monkeypatch) -> None:
    mcp_bootstrap.close_all_mcp_sessions()
    created: list[_FakeStdioSession] = []

    def fake_new(server: LlmMcpServerConfig):
        session = _FakeStdioSession(server.id, mcp_bootstrap._server_fingerprint(server))
        session.ensure_started(server)
        created.append(session)
        return session

    monkeypatch.setattr(mcp_bootstrap, "_new_session", fake_new)
    a = LlmMcpServerConfig(id="demo", transport="stdio", command=["mcp-a"])
    b = LlmMcpServerConfig(id="demo", transport="stdio", command=["mcp-b"])

    mcp_bootstrap.list_mcp_tools(a)
    mcp_bootstrap.list_mcp_tools(b)
    assert len(created) == 2
    mcp_bootstrap.close_all_mcp_sessions()


def test_register_closes_previous_sessions(monkeypatch) -> None:
    mcp_bootstrap.close_all_mcp_sessions()
    closed: list[str] = []

    class Tracking(_FakeStdioSession):
        def close(self) -> None:
            closed.append(self.server_id)

    def fake_new(server: LlmMcpServerConfig):
        session = Tracking(server.id, mcp_bootstrap._server_fingerprint(server))
        session.ensure_started(server)
        return session

    monkeypatch.setattr(mcp_bootstrap, "_new_session", fake_new)
    monkeypatch.setattr(
        mcp_bootstrap,
        "get_llm_config",
        lambda: type(
            "C",
            (),
            {"mcp_servers": [LlmMcpServerConfig(id="demo", transport="stdio", command=["x"])]},
        )(),
    )
    # 先建一个 session
    mcp_bootstrap.list_mcp_tools(LlmMcpServerConfig(id="demo", transport="stdio", command=["x"]))
    assert mcp_bootstrap.mcp_registration_snapshot()["sessions"]
    count = mcp_bootstrap.register_mcp_tools()
    assert count == 1
    assert "demo" in closed
    # register 后会重新 list，应仍有活 session
    assert mcp_bootstrap.mcp_registration_snapshot()["sessions"]
    mcp_bootstrap.close_all_mcp_sessions()
