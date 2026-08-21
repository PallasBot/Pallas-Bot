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
        "【回复形状与输出契约】",
        "【本轮策略】",
        "【刚才的群聊】",
        "【长期记忆】",
        "【知识】",
        "【关系】",
        "【偏好】",
        "【群表达指导】",
    ]
    assert [prompt.index(section) for section in sections] == sorted(prompt.index(section) for section in sections)
    assert prompt.count("我一直都在呀") == 1
    assert "登录昵称" not in prompt
    assert "学习别名" not in prompt
    assert "不要输出 JSON、代码块、括号旁白或 Markdown" in prompt
    assert "先发即时反应" in prompt
    assert "六点？" in prompt


def test_chat_prompt_assembler_renders_behavior_strategy_reference_and_baseline() -> None:
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
            baseline_note="本群真人单条短气泡为主（占比约 83%），单段中位约 6 字。",
            behavior_strategies=[
                ("对方吐槽工作压力", "先短句接住情绪，再问一句具体的事", "对方愿意多讲"),
                ("群里问吃什么", "直接给具体建议", ""),
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

    assert "【真人接话参考】" in prompt
    assert "只借鉴什么时候说短/长、怎么接，不要复刻原话" in prompt
    assert "类似「对方吐槽工作压力」时，真人会先短句接住情绪，再问一句具体的事，结果对方愿意多讲。" in prompt
    assert "类似「群里问吃什么」时，真人会直接给具体建议。" in prompt
    assert "本群真人单条短气泡为主" in prompt
    assert prompt.index("【回复形状与输出契约】") < prompt.index("【群表达指导】") < prompt.index("【真人接话参考】")


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
