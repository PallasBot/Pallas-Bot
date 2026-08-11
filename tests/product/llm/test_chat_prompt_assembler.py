from pallas.product.llm.assembler.chat_prompt import (
    ChatPromptAssembler,
    ResolvedGroupExpression,
)
from pallas.product.llm.assembler.context import ChatContextBundle
from pallas.product.llm.reply_shape import ReplyShapePolicy
from pallas.product.llm.turn_policy import TurnPolicy


def test_chat_prompt_assembler_uses_fixed_order_without_aliases_or_duplicates() -> None:
    prompt = ChatPromptAssembler().assemble(
        core_persona="【核心人格】\n有主见的小姑娘。",
        self_identity="【自称】\n牛牛指自己，使用第一人称。",
        turn_policy=TurnPolicy(
            reply_target="answer",
            seriousness="casual",
            social_action="ANSWER",
            allow_teasing=True,
            allow_affection=True,
            needs_tool=False,
            needs_grounding=False,
        ),
        context=ChatContextBundle(
            memory="【长期记忆】\n- 一起看过戏。",
            knowledge="【知识】\n- 可用命令。",
            relationship="【关系】\n- 老群友。",
            person_facts="【偏好】\n- 喜欢短句。",
        ),
        group_expression=ResolvedGroupExpression(
            style_anchor="短句接梗，别抢戏。",
            matched_examples=[("你又来了", "我一直都在呀"), ("好困", "那就眯一会儿")],
        ),
        reply_shape=ReplyShapePolicy(
            preferred_bubbles=2,
            max_bubbles=3,
            target_chars_min=4,
            target_chars_max=18,
            total_length_band="short",
            rhythm="multi",
            max_output_tokens=80,
        ),
    )

    sections = [
        "【安全约束",
        "【核心人格】",
        "【自称】",
        "【本轮策略】",
        "【长期记忆】",
        "【知识】",
        "【关系】",
        "【偏好】",
        "【群表达指导】",
        "【回复形状与输出契约】",
    ]
    assert [prompt.index(section) for section in sections] == sorted(prompt.index(section) for section in sections)
    assert prompt.count("短句接梗，别抢戏。") == 1
    assert prompt.count("我一直都在呀") == 1
    assert "登录昵称" not in prompt
    assert "学习别名" not in prompt
    assert '"reply_segments"' in prompt
