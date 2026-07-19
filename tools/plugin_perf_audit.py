#!/usr/bin/env python3
"""按插件静态审计 + 动态并发探针（unified 角色插件集）。

用法（仓库根目录）：
  uv run python tools/plugin_perf_audit.py
  uv run python tools/plugin_perf_audit.py --concurrency 32 --iterations 50
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLUGINS_ROOT = ROOT / "packages"

STATIC_PATTERNS: dict[str, tuple[str, int]] = {
    "event_preprocessor": (r"@event_preprocessor", 8),
    "run_preprocessor": (r"@run_preprocessor", 6),
    "on_message": (r"on_message\s*\(", 5),
    "on_command": (r"on_command\s*\(", 4),
    "on_notice": (r"on_notice\s*\(", 4),
    "scheduler": (r"@scheduler\.|add_job\s*\(", 5),
    "httpx_http": (r"httpx\.|AsyncClient\s*\(", 7),
    "aiohttp": (r"aiohttp\.|ClientSession\s*\(", 6),
    "to_thread": (r"asyncio\.to_thread|run_in_executor", 6),
    "file_io": (r"\.read_text\s*\(|\.write_text\s*\(|open\s*\(", 5),
    "db_repo": (r"get_session|_repo\.|Repository|make_.*_repository", 6),
    "claim_gate": (r"try_claim_|message_claims|claim_federate", 7),
    "redis": (r"redis\.|Redis\s*\(", 5),
}

# 插件名 -> (模块路径, 无参同步/异步探针；缺省为 import packages.<name>)
SPECIAL_PROBES: dict[str, tuple[str, str]] = {
    "ingress_gate": ("pallas.core.platform.ingress.gate", "ingress_gate_active"),
}


@dataclass
class StaticReport:
    plugin: str
    py_files: int = 0
    loc: int = 0
    hits: dict[str, int] = field(default_factory=dict)
    risk_score: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class DynamicReport:
    plugin: str
    import_ms: float | None = None
    probe: str | None = None
    concurrency: int = 0
    iterations: int = 0
    total_ms: float | None = None
    avg_ms: float | None = None
    p95_ms: float | None = None
    ops_per_sec: float | None = None
    error: str | None = None


def unified_plugin_names() -> list[str]:
    from pallas.core.platform.bot_runtime.roles import unified_skip_plugin_names

    skip = unified_skip_plugin_names()
    names: list[str] = []
    for entry in sorted(PLUGINS_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if entry.name in skip:
            continue
        if (entry / "__init__.py").is_file():
            names.append(entry.name)
    return names


def scan_plugin_static(name: str) -> StaticReport:
    rep = StaticReport(plugin=name)
    root = PLUGINS_ROOT / name
    if not root.is_dir():
        rep.notes.append("目录不存在")
        return rep
    for path in root.rglob("*.py"):
        if path.name.startswith("."):
            continue
        rep.py_files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            rep.notes.append(f"读失败 {path.name}: {e}")
            continue
        lines = text.splitlines()
        rep.loc += len(lines)
        for key, (pat, weight) in STATIC_PATTERNS.items():
            n = len(re.findall(pat, text))
            if n:
                rep.hits[key] = rep.hits.get(key, 0) + n
                rep.risk_score += n * weight
    if name == "repeater" and rep.hits.get("httpx_http"):
        rep.notes.append("热路径可能走 composite 语料远程 HTTP")
    if name == "ingress_gate":
        rep.notes.append("群消息 event_preprocessor；unified 已 once-claim")
    if name == "pb_webui":
        rep.notes.append("控制台 API；非群消息热路径")
    if name == "pb_stats":
        rep.notes.append("周期心跳；非 per-message")
    return rep


def import_plugin_module(module_path: str):
    return importlib.import_module(module_path)


async def run_probe_bench(
    name: str,
    module_path: str,
    func_name: str,
    *,
    concurrency: int,
    iterations: int,
) -> DynamicReport:
    rep = DynamicReport(plugin=name, concurrency=concurrency, iterations=iterations, probe=func_name)
    t0 = time.perf_counter()
    try:
        mod = await asyncio.to_thread(import_plugin_module, module_path)
        rep.import_ms = (time.perf_counter() - t0) * 1000
    except Exception as e:
        rep.error = f"import: {e}"
        return rep

    fn = getattr(mod, func_name, None)
    if fn is None:
        rep.error = f"无探针 {func_name}"
        return rep
    if func_name == "__name__":
        async def noop(_i: int):
            return mod.__name__

        worker = noop
    elif asyncio.iscoroutinefunction(fn):

        async def worker(_i: int):
            return await fn()

    else:

        async def worker(_i: int):
            return await asyncio.to_thread(fn)

    samples: list[float] = []

    async def one_iter() -> None:
        t1 = time.perf_counter()
        await asyncio.gather(*(worker(i) for i in range(concurrency)))
        samples.append((time.perf_counter() - t1) * 1000)

    try:
        for _ in range(2):
            await one_iter()
        samples.clear()
        await asyncio.gather(*(one_iter() for _ in range(iterations)))
    except Exception as e:
        rep.error = f"bench: {e}"
        return rep

    rep.total_ms = sum(samples)
    rep.avg_ms = statistics.mean(samples)
    rep.p95_ms = statistics.quantiles(samples, n=20)[-1] if len(samples) >= 2 else samples[0]
    total_ops = concurrency * iterations
    rep.ops_per_sec = total_ops / (rep.total_ms / 1000) if rep.total_ms else None
    return rep


async def run_dynamic_for_plugin(
    name: str,
    *,
    concurrency: int,
    iterations: int,
) -> DynamicReport:
    if name in SPECIAL_PROBES:
        mod_path, func = SPECIAL_PROBES[name]
    else:
        mod_path, func = f"packages.{name}", "__name__"
    return await run_probe_bench(name, mod_path, func, concurrency=concurrency, iterations=iterations)


def render_markdown(static_rows: list[StaticReport], dynamic_rows: list[DynamicReport]) -> str:
    lines = [
        "# 插件性能审计（unified）",
        "",
        "## 静态风险（分数越高越需关注热路径）",
        "",
        "| 插件 | LOC | risk | event_pre | on_msg | http | claim | 备注 |",
        "|------|-----|------|-----------|--------|------|-------|------|",
    ]
    for s in sorted(static_rows, key=lambda r: -r.risk_score):
        note = "; ".join(s.notes[:2]) if s.notes else ""
        lines.append(
            f"| {s.plugin} | {s.loc} | {s.risk_score} | {s.hits.get('event_preprocessor', 0)} | "
            f"{s.hits.get('on_message', 0)} | {s.hits.get('httpx_http', 0)} | "
            f"{s.hits.get('claim_gate', 0)} | {note} |"
        )
    lines.extend([
        "",
        "## 动态并发探针",
        "",
        "并发度 × 轮次见各行列；探针为轻量 import + 函数调用。",
        "",
        "| 插件 | import_ms | avg_ms | p95_ms | ops/s | 错误 |",
        "|------|-----------|--------|--------|-------|------|",
    ])

    def fmt(v: float | None, spec: str = ".1f") -> str:
        return format(v, spec) if v is not None else "-"

    for d in dynamic_rows:
        lines.append(
            f"| {d.plugin} | {fmt(d.import_ms)} | {fmt(d.avg_ms)} | "
            f"{fmt(d.p95_ms)} | {fmt(d.ops_per_sec, '.0f')} | {d.error or ''} |"
        )
    return "\n".join(lines) + "\n"


def ensure_nonebot_for_import_probe() -> None:
    """动态探针需 import 插件包；最小化 init 避免 NoneBot has not been initialized。"""
    from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ

    apply_repo_settings_to_environ()
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


async def main_async(args: argparse.Namespace) -> int:
    ensure_nonebot_for_import_probe()
    names = unified_plugin_names()
    static_rows = [scan_plugin_static(n) for n in names]
    dynamic_rows: list[DynamicReport] = []
    for n in names:
        dynamic_rows.append(
            await run_dynamic_for_plugin(n, concurrency=args.concurrency, iterations=args.iterations)
        )

    out_dir = ROOT / "data" / "bot"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "concurrency": args.concurrency,
        "iterations": args.iterations,
        "plugins": names,
        "static": [asdict(s) for s in static_rows],
        "dynamic": [asdict(d) for d in dynamic_rows],
    }
    json_path = out_dir / "plugin_perf_report.json"
    md_path = out_dir / "plugin_perf_report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(static_rows, dynamic_rows), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    top = sorted(static_rows, key=lambda r: -r.risk_score)[:5]
    print("Top static risk:", ", ".join(f"{t.plugin}({t.risk_score})" for t in top))
    slow = sorted(
        [d for d in dynamic_rows if d.avg_ms is not None],
        key=lambda r: -r.avg_ms,
    )[:5]
    print("Slowest dynamic avg_ms:", ", ".join(f"{t.plugin}({t.avg_ms:.2f})" for t in slow))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-plugin static + concurrent perf audit")
    parser.add_argument("--concurrency", type=int, default=24, help="并发协程数（每轮）")
    parser.add_argument("--iterations", type=int, default=30, help="基准轮次")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
