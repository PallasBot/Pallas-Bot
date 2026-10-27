from __future__ import annotations

import argparse  # noqa: TC003
import json
import sys


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("mcp", help="本地 Arknights/PRTS 只读 MCP 服务与凭据管理")
    actions = parser.add_subparsers(dest="mcp_action", required=True)

    serve_parser = actions.add_parser("serve", help="在独立 HTTP 端口启动只读 MCP 服务")
    serve_parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    serve_parser.add_argument("--port", type=int, default=8765, help="监听端口")
    serve_parser.add_argument("--allow-remote", action="store_true", help="允许非回环监听（需显式配置 Host）")
    serve_parser.add_argument(
        "--allowed-host", action="append", default=None, metavar="HOST", help="精确 Host 值，可重复"
    )
    serve_parser.add_argument(
        "--allowed-origin", action="append", default=[], metavar="ORIGIN", help="精确 HTTP(S) Origin，可重复"
    )
    serve_parser.add_argument("--rate-limit", type=int, default=60, help="每个 MCP Key 的请求数")
    serve_parser.add_argument("--rate-window", type=int, default=60, help="限流窗口秒数")
    serve_parser.add_argument("--concurrency", type=int, default=8, help="最大并发请求和查询线程数")
    serve_parser.add_argument("--max-request-body-size", type=int, default=64 * 1024, help="请求体上限（字节）")
    serve_parser.add_argument("--source-url", default=None, help="在 MCP 初始化说明中公布本运行版源码归档 URL")
    serve_parser.set_defaults(handler=serve)

    token_parser = actions.add_parser("token", help="签发一次性显示的 MCP 专用 Bearer Key")
    token_parser.add_argument("--label", default="", help="凭据备注")
    token_parser.add_argument(
        "--scope",
        action="append",
        choices=("arknights:read", "prts:read"),
        default=None,
        help="授予只读范围，可重复；默认两种范围",
    )
    token_parser.set_defaults(handler=issue_token)

    actions.add_parser("tokens", help="列出 MCP Key 元数据（不含密钥或哈希）").set_defaults(handler=list_tokens)
    revoke_parser = actions.add_parser("revoke", help="撤销 MCP Key")
    revoke_parser.add_argument("id", help="Key ID")
    revoke_parser.set_defaults(handler=revoke_token)

    corpus = actions.add_parser("corpus", help="管理本地 PRTS 语料快照")
    corpus_actions = corpus.add_subparsers(dest="corpus_action", required=True)
    corpus_actions.add_parser("status", help="查看语料状态").set_defaults(handler=corpus_status)
    corpus_actions.add_parser("update", help="下载并发布语料快照").set_defaults(handler=corpus_update)


def issue_token(args: argparse.Namespace) -> int:
    from pallas.product.arknights_mcp.auth import CredentialStore

    secret, key_id = CredentialStore().issue(label=args.label, scopes=args.scope)
    print("MCP Bearer Key（仅显示一次，请妥善保存）:")
    print(f"  id:     {key_id}")
    print(f"  label:  {args.label.strip() or '-'}")
    print(f"  scopes: {', '.join(args.scope or ('arknights:read', 'prts:read'))}")
    print(f"  key:    {secret}")
    return 0


def list_tokens(_args: argparse.Namespace) -> int:
    from pallas.product.arknights_mcp.auth import CredentialStore

    rows = CredentialStore().list()
    if not rows:
        print("没有已签发的 MCP Key。可用 `pallas mcp token` 签发。")
        return 0
    print(f"{'id':<18} {'label':<20} {'scopes':<30} created_at")
    for row in rows:
        print(f"{row['id']:<18} {str(row['label'])[:20]:<20} {', '.join(row['scopes']):<30} {row['created_at']}")
    return 0


def revoke_token(args: argparse.Namespace) -> int:
    from pallas.product.arknights_mcp.auth import CredentialStore

    if CredentialStore().revoke(args.id):
        print(f"已撤销 MCP Key [{args.id}]")
        return 0
    print(f"未找到 MCP Key [{args.id}]", file=sys.stderr)
    return 1


def serve(args: argparse.Namespace) -> int:
    import uvicorn

    from pallas.product.arknights_mcp.server import create_app

    try:
        app = create_app(
            host=args.host,
            port=args.port,
            allow_remote=args.allow_remote,
            allowed_hosts=args.allowed_host,
            allowed_origins=args.allowed_origin,
            rate_limit=args.rate_limit,
            rate_window_seconds=args.rate_window,
            concurrency=args.concurrency,
            max_request_body_size=args.max_request_body_size,
            source_url=args.source_url,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"MCP 服务配置失败：{exc}", file=sys.stderr)
        return 2
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, access_log=False)
    return 0


def corpus_status(_args: argparse.Namespace) -> int:
    from pallas.product.arknights_kb.prts_runtime import corpus_status as get_status

    print(json.dumps(get_status(), ensure_ascii=False, indent=2))
    return 0


def corpus_update(_args: argparse.Namespace) -> int:
    from pallas.product.arknights_kb.prts_runtime import update_corpus

    result = update_corpus()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1
