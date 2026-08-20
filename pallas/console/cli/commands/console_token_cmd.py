"""`pallas console token`：签发 / 列出 / 吊销长期 API Key 供本地 agent 访问控制台 API。"""

from __future__ import annotations

import argparse  # noqa: TC003
import sys


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("console", help="控制台鉴权与 API Key 管理")
    tok_sub = parser.add_subparsers(dest="console_action", required=True)
    create = tok_sub.add_parser("token", help="签发新的 API Key")
    create.add_argument("--label", default="", help="备注（默认为空）")
    create.set_defaults(handler=create_token)

    tok_sub.add_parser("tokens", help="列出已有 API Key（不含明文）").set_defaults(handler=list_tokens)
    revoke = tok_sub.add_parser("revoke", help="吊销指定 id 的 API Key")
    revoke.add_argument("id", help="API Key id")
    revoke.set_defaults(handler=revoke_token)


def create_token(args: argparse.Namespace) -> int:
    from pallas.console.webui.console_login import issue_api_key

    secret, key_id = issue_api_key(label=args.label)
    print("已签发 API Key（仅显示一次，请妥善保存）:")
    print(f"  id:      {key_id}")
    print(f"  label:   {args.label or '-'}")
    print(f"  密钥:    {secret}")
    print()
    print("用法:")
    print(f'  curl -H "X-Pallas-Api-Key: {secret}" http://127.0.0.1:8088/pallas/api/...')
    return 0


def list_tokens(_args: argparse.Namespace) -> int:
    from pallas.console.webui.console_login import list_api_keys

    rows = list_api_keys()
    if not rows:
        print("没有已签发的 API Key。可用 `pallas console token` 签发。")
        return 0
    print(f"{'id':<14} {'label':<20} {'created_at':<22} last_used_at")
    for r in rows:
        print(f"{r['id']:<14} {r['label'][:20]:<20} {r['created_at']:<22} {r['last_used_at']}")
    return 0


def revoke_token(args: argparse.Namespace) -> int:
    from pallas.console.webui.console_login import revoke_api_key

    if revoke_api_key(args.id):
        print(f"已吊销 API Key [{args.id}]")
        return 0
    print(f"未找到 API Key [{args.id}]", file=sys.stderr)
    return 1
