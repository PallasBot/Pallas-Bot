from __future__ import annotations

import sys
from types import ModuleType

from pallas.console.cli.main import build_parser
from pallas.product.arknights_mcp import auth


def test_mcp_cli_defaults_to_loopback_and_known_free_port():
    args = build_parser().parse_args(["mcp", "serve"])
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.allow_remote is False
    assert args.allowed_host is None
    assert args.allowed_origin == []
    assert args.concurrency == 8


def test_cli_token_commands_do_not_use_console_credentials(monkeypatch, capsys):
    class FakeStore:
        def issue(self, **kwargs):
            assert kwargs == {"label": "client", "scopes": ["prts:read"]}
            return "pmcp_one-time", "0123456789abcdef"

        def list(self):
            return [{"id": "0123456789abcdef", "label": "client", "scopes": ["prts:read"], "created_at": "now"}]

        def revoke(self, key_id):
            assert key_id == "0123456789abcdef"
            return True

    monkeypatch.setattr(auth, "CredentialStore", FakeStore)
    parser = build_parser()
    from pallas.console.cli.commands import mcp_cmd

    assert mcp_cmd.issue_token(parser.parse_args(["mcp", "token", "--label", "client", "--scope", "prts:read"])) == 0
    issued = capsys.readouterr().out
    assert "pmcp_one-time" in issued
    assert "pls_" not in issued

    assert mcp_cmd.list_tokens(parser.parse_args(["mcp", "tokens"])) == 0
    listed = capsys.readouterr().out
    assert "pmcp_one-time" not in listed
    assert "hash" not in listed

    assert mcp_cmd.revoke_token(parser.parse_args(["mcp", "revoke", "0123456789abcdef"])) == 0


def test_serve_uses_configured_app_and_disables_proxy_header_trust(monkeypatch):
    import uvicorn

    from pallas.console.cli.commands import mcp_cmd
    from pallas.product.arknights_mcp import server

    calls = {}
    app = object()

    def create_app(**kwargs):
        calls["app_config"] = kwargs
        return app

    monkeypatch.setattr(server, "create_app", create_app)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.update(app=app, uvicorn=kwargs))
    args = build_parser().parse_args(["mcp", "serve"])

    assert mcp_cmd.serve(args) == 0
    assert calls["app"] is app
    assert calls["app_config"]["host"] == "127.0.0.1"
    assert calls["app_config"]["port"] == 8765
    assert calls["uvicorn"] == {"host": "127.0.0.1", "port": 8765, "proxy_headers": False}


def test_corpus_cli_calls_only_explicit_status_and_update(monkeypatch, capsys):
    calls = []
    module = ModuleType("pallas.product.arknights_kb.prts_runtime")
    module.corpus_status = lambda: calls.append("status") or {"ready": True}
    module.update_corpus = lambda: calls.append("update") or {"ok": True}
    monkeypatch.setitem(sys.modules, module.__name__, module)

    from pallas.console.cli.commands import mcp_cmd

    assert mcp_cmd.corpus_status(None) == 0
    assert '"ready": true' in capsys.readouterr().out
    assert mcp_cmd.corpus_update(None) == 0
    assert '"ok": true' in capsys.readouterr().out
    assert calls == ["status", "update"]
