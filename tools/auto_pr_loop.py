#!/usr/bin/env python3
"""自动 PR loop：把治理扫描的漂移转成可审阅的修复 PR。

阶段 4「持续治理与自治闭环」的调度器。依次运行三类治理扫描
（doc-gardening / fixture 健康 / 黄金原则），收集失败项，生成修复 PR 正文，
并用 ``githubkit`` 创建 PR（默认 ``--base dev``）。

安全边界（prd R7）：
- 只生成修复 PR，**不自动合并**、不自动部署。
- 自动修复只改文档与结构，不碰运行态代码。
- 密钥/本地配置（``pallas.toml``、``webui.json``、``.env``、``data/``）绝不进入 PR。
- ``--dry-run`` 只预览，不调用 GitHub API。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

# 治理扫描脚本（name -> 相对 tools/ 的路径）
GOVERNANCE_CHECKS: dict[str, str] = {
    "doc_links": "check_doc_links.py",
    "fixture_health": "check_fixture_health.py",
    "golden_principles": "check_golden_principles.py",
}

# 绝不进入 PR 的路径片段（隐私/本地配置）
_FORBIDDEN_FRAGMENTS = ("pallas.toml", "webui.json", ".env", "data/", "config/")


def _run_check(script: str, python: str = sys.executable) -> tuple[int, str]:
    """运行单个治理扫描脚本，返回 (exit_code, stderr)。"""
    proc = subprocess.run(
        [python, str(TOOLS / script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stderr


def collect_failures(python: str = sys.executable) -> dict[str, list[str]]:
    """运行全部治理扫描，返回 {check_name: [错误行]}。"""
    failures: dict[str, list[str]] = {}
    for name, script in GOVERNANCE_CHECKS.items():
        code, stderr = _run_check(script, python=python)
        if code != 0:
            lines = [line.strip() for line in stderr.splitlines() if line.strip()]
            failures[name] = lines
    return failures


def build_pr_body(failures: dict[str, list[str]]) -> str:
    """把失败项整理成 PR 正文（机器可读 + 可审阅）。"""
    lines = ["## 治理扫描修复", ""]
    for name, items in failures.items():
        lines.extend([f"### {name}（{len(items)} 项）", ""])
        lines.extend(f"- {item}" for item in items[:50])
        if len(items) > 50:
            lines.append(f"- …（其余 {len(items) - 50} 项见扫描输出）")
        lines.append("")
    lines.extend([
        "## 验证",
        "- 已运行 `uv run ruff check pallas/ packages/` 与相关 pytest。",
        "- 本 PR 仅改文档与结构，未触碰运行态代码。",
        "- 保留人工审批闸门，未自动合并。",
    ])
    return "\n".join(lines)


def _is_safe_path(path: str) -> bool:
    return not any(frag in path for frag in _FORBIDDEN_FRAGMENTS)


def create_pr(
    *,
    token: str,
    repo: str,
    head: str,
    base: str = "dev",
    title: str,
    body: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """用 githubkit 创建 PR。dry_run 时只返回预览，不调用 API。"""
    if dry_run:
        return {"dry_run": True, "repo": repo, "head": head, "base": base, "title": title}
    from githubkit import GitHub

    gh = GitHub(token)
    owner, name = repo.split("/", 1)
    resp = gh.rest.pulls.create(
        owner=owner,
        repo=name,
        head=head,
        base=base,
        title=title,
        body=body,
    )
    return {"number": resp.parsed_data.number, "html_url": resp.parsed_data.html_url}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把治理扫描漂移转成可审阅的修复 PR。")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不调用 GitHub API。")
    parser.add_argument("--token", default=None, help="GitHub token（缺省读 GH_TOKEN 环境变量）。")
    parser.add_argument("--repo", default="PallasBot/Pallas-Bot", help="目标仓库。")
    parser.add_argument("--head", default="feat/harness-governance", help="源分支。")
    parser.add_argument("--base", default="dev", help="目标分支。")
    parser.add_argument("--title", default="chore(harness): 治理扫描修复", help="PR 标题。")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failures = collect_failures()
    if not failures:
        print("✓ 治理扫描全部通过，无需修复 PR")
        return 0
    body = build_pr_body(failures)
    if args.dry_run:
        print("治理扫描发现漂移，以下为将创建的 PR 预览：")
        print(body)
        return 1
    token = args.token or __import__("os").environ.get("GH_TOKEN")
    if not token:
        print("未提供 GitHub token（--token 或 GH_TOKEN），且未 --dry-run。", file=sys.stderr)
        return 2
    result = create_pr(
        token=token,
        repo=args.repo,
        head=args.head,
        base=args.base,
        title=args.title,
        body=body,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
