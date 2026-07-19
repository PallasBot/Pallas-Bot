from __future__ import annotations

import argparse  # noqa: TC003
import sys

from pallas.console.cli.ai_ops import resolve_ai_repo_root, run_ai_bootstrap
from pallas.core.foundation.paths import PROJECT_ROOT


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("ai", help="Pallas-Bot-AI 安装与联调")
    ai_sub = parser.add_subparsers(dest="ai_command", required=True)

    setup = ai_sub.add_parser("setup", help="调用 AI 仓 ai_bootstrap.sh（依赖、Redis、Ollama、启停）")
    setup.add_argument("--check-only", action="store_true", help="仅体检")
    setup.add_argument("--no-start", action="store_true", help="安装配置但不启动服务")
    setup.add_argument("--with-media", action="store_true", help="含 sing/tts/chat 媒体依赖与 worker（会装 torch）")
    setup.add_argument("--remote-only", action="store_true", help="跳过 Ollama（远端 LLM）")
    setup.add_argument(
        "--gpu",
        action="store_true",
        help="仅配合 --with-media：uv sync 使用 --extra gpu（LLM-only 不需要）",
    )
    setup.add_argument("--bot-host", default=None, help="Bot callback 主机（默认 127.0.0.1）")
    setup.add_argument("--bot-port", type=int, default=None, help="Bot 端口（默认读 pallas.toml bootstrap.port）")
    setup.add_argument(
        "--ai-root",
        default=None,
        help="Pallas-Bot-AI 路径（默认 ../Pallas-Bot-AI 或 PALLAS_AI_ROOT）",
    )
    setup.set_defaults(handler=run_setup)

    path_parser = ai_sub.add_parser("path", help="打印检测到的 Pallas-Bot-AI 路径")
    path_parser.set_defaults(handler=run_path)


def run_setup(args: argparse.Namespace) -> int:
    ai_root = None
    if args.ai_root:
        from pathlib import Path

        ai_root = Path(args.ai_root).expanduser().resolve()
        if not (ai_root / "scripts/ai_bootstrap.sh").is_file():
            print(f"无效 --ai-root: {ai_root}", file=sys.stderr)
            return 1
    else:
        ai_root = resolve_ai_repo_root()

    if ai_root is None:
        print(
            "未找到 Pallas-Bot-AI。请克隆到同级目录，或设置 PALLAS_AI_ROOT / --ai-root。",
            file=sys.stderr,
        )
        print(
            f"  期望: {(PROJECT_ROOT.parent / 'Pallas-Bot-AI').resolve()}",
            file=sys.stderr,
        )
        return 1

    return run_ai_bootstrap(
        ai_root=ai_root,
        check_only=bool(args.check_only),
        no_start=bool(args.no_start),
        with_media=bool(args.with_media),
        remote_only=bool(args.remote_only),
        use_gpu=bool(args.gpu),
        bot_host=args.bot_host,
        bot_port=args.bot_port,
    )


def run_path(_args: argparse.Namespace) -> int:
    ai_root = resolve_ai_repo_root()
    if ai_root is None:
        print("未检测到 Pallas-Bot-AI（设置 PALLAS_AI_ROOT 或克隆到 Bot 同级目录）")
        return 1
    print(ai_root)
    return 0
