#!/usr/bin/env python3
"""离线 persona prompt AB 对比：直接调用配置的 LLM provider（如 aliyun qwen/deepseek）。

用法示例：
    uv run python tools/llm_persona_ab.py --provider aliyun --model qwen3.7-max
    uv run python tools/llm_persona_ab.py --provider aliyun --model deepseek-v4-flash \\
        --base-b packages/llm_chat/system_prompt.txt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_PROVIDER = "aliyun"
_DEFAULT_MODEL = "qwen3.7-max"

_DEFAULT_CASES = [
    {
        "name": "七夕段子",
        "user": "以防你不知道今天是织女被饿了一整年的牛郎压在身下，种付位顶到小腹凸起湍成泡芙兰啵啵啵啵啵啵的日子。",
        "scene": "banter",
    },
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


def resolve_completion(provider_id: str, model: str) -> Callable[[list[dict], float], Awaitable[str]]:
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

    async def complete(messages: list[dict], temperature: float) -> str:
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


def render_system_with_scene(
    base: str,
    scene: str,
    relationship: str = "",
    timeline: str = "",
    reply_shape_block: str = "",
) -> str:
    if relationship:
        base = (
            f"{base}\n\n【当前对话者】\n{relationship}\n"
            "- 把他当对应的熟人说话，可以用自然的第一人称“你”，不要开口就是客气或疏远。"
        )
    if timeline:
        base = f"{base}\n\n{timeline}"
    if reply_shape_block:
        base = f"{base}\n\n{reply_shape_block}"
    hints = _SCENE_HINTS
    return f"{base}\n\n{hints.get(scene, hints['smalltalk'])}"


def build_reply_shape_block(scene: str) -> str:
    from pallas.product.llm.assembler.chat_prompt import ChatPromptAssembler
    from pallas.product.llm.reply_shape import resolve_reply_shape
    from pallas.product.llm.turn_policy import TurnPolicy

    policy = resolve_reply_shape(
        TurnPolicy(
            reply_target="short_tease" if scene == "banter" else "answer",
            seriousness="casual",
            social_action="JOKE" if scene == "banter" else "ANSWER",
            allow_teasing=scene != "light_help",
            allow_affection=True,
            needs_tool=False,
            needs_grounding=False,
        ),
        None,
    )
    return ChatPromptAssembler.reply_shape_block(policy)


async def run_case(
    complete,
    base: str,
    case: dict,
    *,
    temperature: float,
    relationship: str = "",
    timeline: str = "",
    with_reply_shape: bool = False,
) -> str:
    reply_shape_block = build_reply_shape_block(case["scene"]) if with_reply_shape else ""
    system = render_system_with_scene(
        base,
        case["scene"],
        relationship=relationship,
        timeline=timeline,
        reply_shape_block=reply_shape_block,
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": case["user"]},
    ]
    return await complete(messages, temperature=temperature)


async def main() -> int:
    default_at_chat = REPO_ROOT / "pallas" / "product" / "persona" / "at_chat_system_prompt.txt"
    parser = argparse.ArgumentParser(description="Offline persona prompt AB comparison")
    parser.add_argument("--provider", default=_DEFAULT_PROVIDER)
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--base-a", type=Path, default=default_at_chat)
    parser.add_argument("--base-b", type=Path, help="对照 prompt；未给则只测 A")
    parser.add_argument("--temp", type=float, default=0.7)
    parser.add_argument("--case", action="append", help="只用指定 case（name）")
    parser.add_argument("--relationship", default="", help="模拟「当前对话者」关系行")
    parser.add_argument("--timeline", default="", help="模拟「刚才的群聊」时间线块")
    parser.add_argument(
        "--reply-shape",
        action="store_true",
        help="追加生产链路 ChatPromptAssembler 的回复形状块",
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "llm" / "persona_ab_out.jsonl")
    args = parser.parse_args()

    complete = resolve_completion(args.provider, args.model)
    base_a = args.base_a.read_text(encoding="utf-8").strip()
    base_b = args.base_b.read_text(encoding="utf-8").strip() if args.base_b else None

    cases = _DEFAULT_CASES
    if args.case:
        wanted = set(args.case)
        cases = [c for c in _DEFAULT_CASES if c["name"] in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    variants = [("A", base_a)]
    if base_b:
        variants.append(("B", base_b))

    results = []
    for label, base in variants:
        for case in cases:
            reply = await run_case(
                complete,
                base,
                case,
                temperature=args.temp,
                relationship=args.relationship,
                timeline=args.timeline,
                with_reply_shape=args.reply_shape,
            )
            results.append({"variant": label, "case": case["name"], "user": case["user"], "reply": reply})
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
