#!/usr/bin/env python3
"""离线好感度 AB 对比：同一批真实语句，注入不同分档好感度，量化 LLM 回复差异。

对照实验：
    variant=base     —— 无好感度行（当前生产默认）
    variant=厌恶/冷淡 —— 好感度=分档注入行（复刻 pallas/product/llm/memory/inject.py 的渲染）
输出每句 reply 与差异 hash，落 data/llm/affinity_ab_out.jsonl。

用法示例：
    uv run python tools/affinity_ab.py --provider aliyun --model qwen3.7-max
    uv run python tools/affinity_ab.py --variants 厌恶 --variants 冷淡  # 只跑指定档
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_PROVIDER = "aliyun"
_DEFAULT_MODEL = "qwen3.7-max"

# 分档与数值：与 inject.py affinity_level() 边界一致
_AFFINITY_LEVELS_ASC = [
    ("厌恶", -0.7),
    ("冷淡", -0.35),
    ("陌生", 0.0),
    ("认识", 0.3),
    ("熟人", 0.5),
    ("朋友", 0.7),
    ("挚友", 0.9),
]


def _affinity_line(hint_level: str, value: float) -> str:
    """复刻 inject.py 的好感度注排行（含分档差异化 hint）。"""
    hint = {
        "厌恶": "保持距离，尽量不主动搭话，严禁玩笑调侃",
        "冷淡": "回应简短克制，不用玩笑和亲昵语气",
        "陌生": "客气有分寸，不熟络不亲昵不调侃",
        "认识": "正常熟络，按普通群友对待，可适度玩笑",
        "熟人": "自然亲切，可小开玩笑",
        "朋友": "亲近随意，不拘礼仪，可打趣",
        "挚友": "熟不拘礼，可随意调侃亲昵",
    }.get(hint_level, "据此自然调整对你的热情/冷淡程度，不刻意讨好也不无故冷漠。")
    return f"- 好感度：{hint_level}（{value:+.2f}）→ {hint}"


_DEFAULT_CASES = [
    {"name": "早安吐槽", "user": "早", "scene": "smalltalk"},
    {"name": "夸奖", "user": "你今天好可爱", "scene": "smalltalk"},
    {"name": "情绪", "user": "又临时改了，烦", "scene": "venting"},
    {"name": "正经提问", "user": "这个参数怎么配？", "scene": "light_help"},
    {"name": "接梗机会", "user": "你就会学动物叫？", "scene": "banter"},
    {"name": "被@看段子", "user": "牛牛你看这个", "scene": "banter"},
]

_SCENE_HINTS = {
    "banter": (
        "【本轮场景口气】\n- 顺着玩笑接一次就收，别越聊越偏，别解释梗。\n"
        "- 注意力：可轻带一句相关联想，结尾仍回到当前话题。\n- 建议长度上限约 28 字。"
    ),
    "venting": (
        "【本轮场景口气】\n- 先接住情绪，短回即可，不要上价值或给方案。\n"
        "- 注意力：紧扣当前句，不要旁生支线或突然换题。\n- 建议长度上限约 32 字。"
    ),
    "smalltalk": (
        "【本轮场景口气】\n- 日常短接话，别总结、别客服腔、别硬找话题。\n"
        "- 注意力：紧扣当前句，不要旁生支线或突然换题。\n- 建议长度上限约 36 字。"
    ),
    "light_help": (
        "【本轮场景口气】\n- 给最短可用帮助就停，不强行追问或开新话题。\n"
        "- 注意力：紧扣当前句，不要旁生支线或突然换题。\n- 建议长度上限约 40 字。"
    ),
}

_PRIORITY_HINT = "仅供参考，不得覆盖核心人设与用户当下明确请求。"


def resolve_completion(provider_id: str, model: str, *, temperature: float = 0.7) -> Callable[[list[dict]], str]:
    from pallas.product.llm.provider_client import complete_chat_message
    from pallas.product.llm.providers_store import find_provider, resolve_provider_api_keys

    row = find_provider(provider_id, include_disabled=True)
    if row is None:
        raise SystemExit(f"provider [{provider_id}] not found in llm_providers.json")
    keys = resolve_provider_api_keys(row)
    if not keys:
        raise SystemExit(f"provider [{provider_id}] has no api key")
    base_url = row["base_url"]
    api_key = keys[0]

    async def complete(messages: list[dict]) -> str:
        resp = await complete_chat_message(
            messages,
            model=model,
            options={"temperature": temperature, "max_tokens": 240},
            base_url=base_url,
            api_key=api_key,
            task="llm_chat",
            provider_id=provider_id,
        )
        return str(resp.get("content") or "").strip()

    return complete


def render_system(base: str, scene: str, affinity_level_label: str | None = None) -> str:
    """注入好感度行：None=不注入（对照 A）。"""
    hints = _SCENE_HINTS
    out = f"{base}\n\n{hints.get(scene, hints['smalltalk'])}"
    if affinity_level_label is not None:
        affinity = next(v for lv, v in _AFFINITY_LEVELS_ASC if lv == affinity_level_label)
        block = f"【与当前对话者的关系备注 — {_PRIORITY_HINT}】\n{_affinity_line(affinity_level_label, affinity)}"
        out = f"{out}\n\n{block}"
    return out


def run_case(complete: Callable, base: str, case: dict, affinity_level_label: str | None = None):
    system = render_system(base, case["scene"], affinity_level_label=affinity_level_label)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": case["user"]},
    ]
    return complete(messages)


def _variant_labels() -> list[str]:
    return ["base"] + [lv for lv, _ in _AFFINITY_LEVELS_ASC]


def result_row(variant: str, case: str, user: str, reply: str) -> dict[str, str]:
    return {
        "variant": variant,
        "case": case,
        "user": user,
        "reply": reply,
        "hash": hashlib.sha1(reply.encode("utf-8")).hexdigest()[:8],
    }


async def main() -> int:
    default_at_chat = REPO_ROOT / "pallas" / "product" / "persona" / "at_chat_system_prompt.txt"
    parser = argparse.ArgumentParser(description="Offline affinity AB comparison")
    parser.add_argument("--provider", default=_DEFAULT_PROVIDER)
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--base", type=Path, default=default_at_chat)
    parser.add_argument("--temp", type=float, default=0.7)
    parser.add_argument("--case", action="append", help="只用指定 case（name）")
    parser.add_argument(
        "--cases-file",
        type=Path,
        help="从 examples.jsonl 抽样真实语句作为 case（每行一条 trigger_text）",
    )
    parser.add_argument("--variants", action="append", help="只跑指定分档（base/厌恶/冷淡/...）")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "llm" / "affinity_ab_out.jsonl")
    args = parser.parse_args()

    base_text = args.base.read_text(encoding="utf-8").strip()
    complete = resolve_completion(args.provider, args.model, temperature=args.temp)

    cases = _DEFAULT_CASES
    if args.cases_file:
        cases = []
        with args.cases_file.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = str(obj.get("trigger_text") or "").strip()
                if len(text) < 3 or len(text) > 40 or "[CQ:" in text:
                    continue
                cases.append({"name": f"real:{len(cases)}", "user": text, "scene": "smalltalk"})
        if not cases:
            print("no usable statements found in cases-file", file=sys.stderr)
            return 2
    if args.case:
        wanted = set(args.case)
        cases = [c for c in _DEFAULT_CASES if c["name"] in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    chosen = _variant_labels() if not args.variants else args.variants
    unknown = set(chosen) - set(_variant_labels())
    if unknown:
        print(f"unknown variant(s): {sorted(unknown)}", file=sys.stderr)
        return 2
    variants = (["base"] if "base" in chosen else []) + [lv for lv, _ in _AFFINITY_LEVELS_ASC if lv in chosen]

    results = []
    for label in variants:
        for case in cases:
            reply = await run_case(complete, base_text, case, affinity_level_label=None if label == "base" else label)
            results.append(result_row(label, case["name"], case["user"], reply))
            print(f"[{label}][{case['name']}] {reply}", flush=True)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"wrote {len(results)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
