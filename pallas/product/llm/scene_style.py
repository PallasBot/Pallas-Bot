"""按会话场景派生口气约束与注意力漂移档。"""

from __future__ import annotations

from typing import Literal

from pallas.product.llm.kernel.models import ConversationMode, ConversationScene, DecisionConstraints

DriftLevel = Literal["strict", "balanced", "loose"]

_DRIFT_RULES: dict[DriftLevel, str] = {
    "strict": "紧扣当前句，不要旁生支线或突然换题。",
    "balanced": "可轻带一句相关联想，结尾仍回到当前话题。",
    "loose": "允许一次可理解的拐弯，但不要无视明确提问。",
}

_SCENE_STYLE: dict[ConversationScene, tuple[str, DriftLevel, int]] = {
    # style_hint, drift_level, max_length_cap (0 = 不额外收紧)
    ConversationScene.BANTER: ("顺着玩笑接一次就收，别越聊越偏，别解释梗。", "balanced", 28),
    ConversationScene.VENTING: ("先接住情绪，短回即可，不要上价值或给方案。", "strict", 32),
    ConversationScene.PROVOCATION: ("怪话轻吐槽一句就收，别认真辩论，别扩成说教。", "strict", 24),
    ConversationScene.GROUP_THREADING: ("多人插话时只抓一个锚点；旁观位默认少插，别占别人的「我/你」。", "strict", 28),
    ConversationScene.LIGHT_HELP: ("给最短可用帮助就停，不强行追问或开新话题。", "strict", 40),
    ConversationScene.SMALLTALK: ("日常短接话，别总结、别客服腔、别硬找话题。", "strict", 36),
    ConversationScene.IDLE_OPPORTUNITY: ("有话再说，没有就别硬开口；一句以内。", "strict", 20),
    ConversationScene.HOSTED_CONTEXT: ("跟着当前主持/活动语境短接，别抢主持。", "balanced", 32),
}


def resolve_scene_style_constraints(
    scene: ConversationScene | str | None,
    mode: ConversationMode = ConversationMode.NORMAL,
    *,
    direct_chat: bool = False,
) -> DecisionConstraints:
    from pallas.product.llm.kernel.models import behavior_scene_to_conversation_scene

    resolved_scene = scene if isinstance(scene, ConversationScene) else behavior_scene_to_conversation_scene(scene)
    style_hint, drift_level, scene_cap = _SCENE_STYLE.get(
        resolved_scene,
        _SCENE_STYLE[ConversationScene.SMALLTALK],
    )

    if direct_chat:
        max_length = 120
        min_length = 1
        if drift_level == "strict":
            drift_level = "balanced"
    elif mode == ConversationMode.GHOST:
        max_length = 18
        min_length = 1
        drift_level = "strict"
    elif mode == ConversationMode.GOD:
        max_length = 48
        min_length = 2
    else:
        max_length = 36
        min_length = 1

    if not direct_chat and scene_cap > 0:
        max_length = min(max_length, scene_cap)

    return DecisionConstraints(
        max_length=max_length,
        min_length=min_length,
        disallow_drift=drift_level == "strict",
        disallow_service_tone=True,
        drift_level=drift_level,
        style_hint=style_hint,
    )


def format_scene_style_block(constraints: DecisionConstraints) -> str:
    hint = str(constraints.style_hint or "").strip()
    if not hint:
        return ""
    drift = str(constraints.drift_level or "strict").strip() or "strict"
    drift_rule = _DRIFT_RULES.get(drift, _DRIFT_RULES["strict"])  # type: ignore[arg-type]
    lines = [
        "【本轮场景口气】",
        f"- {hint}",
        f"- 注意力：{drift_rule}",
    ]
    if constraints.max_length > 0:
        lines.append(f"- 建议长度上限约 {int(constraints.max_length)} 字。")
    return "\n".join(lines)
