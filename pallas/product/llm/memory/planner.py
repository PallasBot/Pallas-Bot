"""记忆通道选择的轻量启发式规划器。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryPlan(BaseModel):
    need_session: bool = True
    need_mid_term: bool = False
    need_episodes: bool = False
    need_person: bool = False
    need_relationship: bool = False
    need_graph: bool = False
    reasons: list[str] = Field(default_factory=list)


def plan_memory_retrieval(
    query_text: str,
    *,
    has_mention: bool = False,
    has_relationship_cues: bool = False,
) -> MemoryPlan:
    text = (query_text or "").casefold()
    reasons: list[str] = []
    past = ("记得", "以前", "上次", "曾经", "之前", "过去")
    social = ("谁", "关系", "朋友", "认识", "熟", "他", "她", "这个人")
    group = ("群", "群里", "大家", "梗", "玩笑", "频道")
    if any(word in text for word in past):
        reasons.append("查询包含历史回忆线索")
    if any(word in text for word in group):
        reasons.append("查询包含群体或共同话题线索")
    if has_mention or any(word in text for word in social):
        reasons.append("查询包含人物线索")
    if has_relationship_cues or "关系" in text:
        reasons.append("查询包含关系线索")
    return MemoryPlan(
        need_mid_term=bool(reasons),
        need_episodes=any(word in text for word in past + group),
        need_person=has_mention or any(word in text for word in social),
        need_relationship=has_relationship_cues or "关系" in text,
        need_graph=has_mention or has_relationship_cues or any(word in text for word in group),
        reasons=reasons,
    )
