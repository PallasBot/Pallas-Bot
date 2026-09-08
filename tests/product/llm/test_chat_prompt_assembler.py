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
            group_timeline="【刚才的群聊】\n- 兔兔：还是笨蛋欸",
            memory="【长期记忆】\n- 一起看过戏。",
            knowledge="【知识】\n- 可用命令。",
            relationship="【关系】\n- 老群友。",
            person_facts="【偏好】\n- 喜欢短句。",
        ),
        group_expression=ResolvedGroupExpression(
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
        "【群表达指导】",
        "【长期记忆】",
        "【知识】",
        "【关系】",
        "【偏好】",
        "【刚才的群聊】",
        "【回复形状与输出契约】",
        "【本轮策略】",
    ]
    assert [prompt.index(section) for section in sections] == sorted(prompt.index(section) for section in sections)
    assert prompt.count("我一直都在呀") == 1
    assert "登录昵称" not in prompt
    assert "学习别名" not in prompt
    assert "不要输出 JSON、代码块、括号旁白或 Markdown" in prompt
    assert "先发即时反应" in prompt
    assert "需要多段时按独立意思自然分行" in prompt
    assert "回顶" not in prompt


def test_chat_prompt_assembler_renders_controlled_patterns_and_continuation() -> None:
    from pallas.product.llm.repeater_semantic_style import ContinuationPattern, ControlledBehaviorPattern

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
        context=ChatContextBundle(),
        group_expression=ResolvedGroupExpression(
            matched_examples=[("你又来了", "我一直都在呀")],
            behavior_patterns=[
                ControlledBehaviorPattern(
                    interaction_action="agree",
                    semantic_relation="agree",
                    form="short",
                    intensity="soft",
                    count=3,
                    responder_ids=[11, 12],
                    representative_triggers=["好烦，又加班了"],
                )
            ],
            continuation_patterns=[
                ContinuationPattern(
                    semantic_relation="follow_up",
                    form="question",
                    intensity="neutral",
                    count=3,
                    speaker_ids=[11, 13],
                    representative_triggers=["今天好热"],
                )
            ],
        ),
        reply_shape=ReplyShapePolicy(
            preferred_bubbles=1,
            max_bubbles=3,
            target_chars_min=4,
            target_chars_max=18,
            total_length_band="short",
            rhythm="single",
            max_output_tokens=80,
        ),
    )

    assert "【真人接话模式】" in prompt
    assert "类似「好烦，又加班了」时，本群真人常用认同的方式表示赞同，表述偏短句。" in prompt
    assert "【本群续句习惯】" in prompt
    assert "不要把这种续句误当成两个人对话" in prompt
    # 节奏基线不再由语义指导器注入，生成节奏统一交回 reply_shape
    assert "本群真人单条短气泡为主" not in prompt
    assert "【真人接话参考】" not in prompt
    assert "【接话复盘】" not in prompt
    # 段序按变化频率排布：群表达指导在前，逐轮变化的输出契约靠后。
    assert prompt.index("【群表达指导】") < prompt.index("【真人接话模式】") < prompt.index("【回复形状与输出契约】")


def test_chat_prompt_assembler_renders_cached_semantic_style_block() -> None:
    prompt = ChatPromptAssembler().assemble(
        core_persona="核心",
        self_identity="自称",
        turn_policy=TurnPolicy(
            reply_target="answer",
            seriousness="casual",
            social_action="ANSWER",
            allow_teasing=True,
            allow_affection=True,
            needs_tool=False,
            needs_grounding=False,
        ),
        context=ChatContextBundle(),
        group_expression=ResolvedGroupExpression(
            prompt_block="【本群表达校准】\n可借鉴句式：没救了",
        ),
        reply_shape=ReplyShapePolicy(
            preferred_bubbles=1,
            max_bubbles=2,
            target_chars_min=4,
            target_chars_max=18,
            total_length_band="short",
            rhythm="single",
            max_output_tokens=80,
        ),
    )

    assert "【本群表达校准】" in prompt
    assert "可借鉴句式：没救了" in prompt


def test_chat_prompt_assembler_keeps_quote_replies_within_casual_shape() -> None:
    prompt = ChatPromptAssembler().assemble(
        core_persona="核心",
        self_identity="自称",
        turn_policy=TurnPolicy(
            reply_target="answer",
            seriousness="casual",
            social_action="ANSWER",
            allow_teasing=True,
            allow_affection=True,
            needs_tool=False,
            needs_grounding=False,
        ),
        context=ChatContextBundle(),
        group_expression=None,
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

    assert "引用只决定回复哪条消息" in prompt
    assert "不要因引用把话一次说完" in prompt
    assert "「行啊」「好呀」" in prompt


def test_chat_prompt_complete_band_keeps_light_tone() -> None:
    prompt = ChatPromptAssembler().assemble(
        core_persona="核心",
        self_identity="自称",
        turn_policy=TurnPolicy(
            reply_target="answer",
            seriousness="serious",
            social_action="ANSWER",
            allow_teasing=False,
            allow_affection=False,
            needs_tool=False,
            needs_grounding=True,
        ),
        context=ChatContextBundle(),
        group_expression=None,
        reply_shape=ReplyShapePolicy(
            preferred_bubbles=1,
            max_bubbles=2,
            target_chars_min=8,
            target_chars_max=80,
            total_length_band="complete",
            rhythm="single",
            max_output_tokens=200,
        ),
    )

    assert "语气别收干" in prompt
    assert "别写成书面语或客服腔" in prompt
    assert "先发即时反应" not in prompt
