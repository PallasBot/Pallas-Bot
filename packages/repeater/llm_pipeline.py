from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.product.llm.kernel.generation import GenerationPlan, build_repeater_generation_plan
from pallas.product.llm.kernel.models import ConversationMode, ConversationPath, ConversationScene, GenerationStage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .responder import ReplyBundle


@dataclass(frozen=True)
class RepeaterLlmPlan:
    stage_names: list[str]
    fallback_text: str
    candidate_text: str
    candidate_pool: list[str]
    generation_plan: GenerationPlan | None = None


def build_repeater_llm_plan(
    bundle: ReplyBundle,
    *,
    llm_enabled: bool,
    select_enabled: bool,
    polish_enabled: bool,
    polish_lite_enabled: bool,
) -> RepeaterLlmPlan:
    candidate = next((item for item in bundle.answer_list if item and "[CQ:" not in item), "")
    pool = [item for item in bundle.message_pool if item and "[CQ:" not in item]
    if not llm_enabled:
        return RepeaterLlmPlan([], candidate, candidate, pool)

    stage_names: list[str] = []
    if len(pool) >= 2 and select_enabled:
        stage_names.append("select")
    if (candidate or pool) and (polish_enabled or polish_lite_enabled):
        stage_names.append("rewrite")
    if len(pool) >= 2:
        stage_names.append("stitch")
    if not stage_names or not (pool or candidate):
        stage_names.append("generate")
    elif "generate" not in stage_names:
        stage_names.append("generate")
    stages = [GenerationStage(item) for item in stage_names]
    generation_plan = build_repeater_generation_plan(
        path=ConversationPath.REPEATER_ASSIST,
        stages=stages,
        scene=ConversationScene.SMALLTALK,
        mode=ConversationMode.NORMAL,
        user_text="",
        candidate_pool=pool,
        candidate_text=candidate,
        fallback_text=candidate,
    )
    return RepeaterLlmPlan(stage_names, candidate, candidate, pool, generation_plan)


def build_stitch_candidate(candidate_pool: list[str]) -> str:
    unique = []
    for item in candidate_pool:
        text = str(item or "").strip()
        if not text or "[CQ:" in text or text in unique:
            continue
        unique.append(text)
        if len(unique) >= 2:
            break
    if len(unique) < 2:
        return ""
    left, right = unique[0], unique[1]
    if left == right or left in right or right in left:
        return ""
    if len(left) > 18 or len(right) > 18:
        return ""
    stitched = f"{left}，{right}"
    if len(stitched) > 36:
        return ""
    return stitched


async def run_repeater_llm_plan(
    plan: RepeaterLlmPlan,
    *,
    stage_runner: Callable[[str], Awaitable[bool]],
) -> bool:
    for stage_name in plan.stage_names:
        if await stage_runner(stage_name):
            return True
    return False
