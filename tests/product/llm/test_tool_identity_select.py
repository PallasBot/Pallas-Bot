from __future__ import annotations

import pytest

from pallas.product.llm.tools.identity import is_self_identity_question
from pallas.product.llm.tools.select import infer_tool_domains


@pytest.mark.parametrize(
    "text",
    [
        "你是谁",
        "你是谁？",
        "我又是谁",
        "你知道你是谁吗",
        "@渡月桥 你是谁",
        "[CQ:at,qq=123] 你是谁",
    ],
)
def test_self_identity_does_not_infer_arknights_tools(text: str) -> None:
    assert is_self_identity_question(text)
    assert "arknights" not in infer_tool_domains(text)


@pytest.mark.parametrize(
    "text",
    [
        "银灰是谁",
        "你知道谁是银灰吗",
        "介绍一下能天使",
    ],
)
def test_operator_lookup_still_infers_arknights(text: str) -> None:
    assert not is_self_identity_question(text)
    assert "arknights" in infer_tool_domains(text)


@pytest.mark.parametrize(
    "text",
    [
        "图片里的是谁[CQ:image,url=https://x1,file=a.png]",
        "图片里是谁[CQ:image,url=https://x2,file=b.png,sub_type=1,summary=&#91;动画表情&#93;]",
        "我这个表情包里是谁[CQ:image,url=https://x3,file=c.png]",
        "[CQ:image,url=https://x4,file=d.png] 这个表情里的是谁",
    ],
)
def test_vision_message_does_not_infer_arknights_or_memes(text: str) -> None:
    domains = infer_tool_domains(text)
    assert "arknights" not in domains
    assert "memes" not in domains


def test_infer_drink_and_help_command_domains() -> None:
    assert "drink" in infer_tool_domains("帮牛牛喝一杯")
    assert "drink" in infer_tool_domains("让它醒一醒别喝了")
    assert "drink" in infer_tool_domains("来杯酒")
    assert "help" in infer_tool_domains("看看牛牛帮助")
    assert "help" in infer_tool_domains("有哪些功能")
    assert "help" in infer_tool_domains("有什么功能")
    assert "help" in infer_tool_domains("怎么用")
    assert "llm_chat" in infer_tool_domains("把刚才聊的清空")
    assert "sing" in infer_tool_domains("来唱一首歌")
    assert "sing" in infer_tool_domains("帮我点歌周杰伦")
    assert "sing" in infer_tool_domains("牛牛音乐 晴天")
    assert "sing" in infer_tool_domains("放首歌 海阔天空")
    assert "sing" in infer_tool_domains("来一首稻香")
    assert "command" not in infer_tool_domains("放首歌 铁花飞")
    assert "roulette" in infer_tool_domains("开一局轮盘")
    assert "roulette" in infer_tool_domains("我要开枪")
    assert "dream" in infer_tool_domains("让牛牛做梦")
    assert "duel" in infer_tool_domains("开一场决斗")
    assert "who_is_spy" in infer_tool_domains("来玩卧底")
    assert "arcana" in infer_tool_domains("抽一张塔罗")
    assert "interact" in infer_tool_domains("帮我赞我一下")
    assert "memes" in infer_tool_domains("做个表情包")
    assert "bot_status" in infer_tool_domains("牛牛报数")
    assert "maa" in infer_tool_domains("牛牛长草")
    assert "afdian" in infer_tool_domains("查一下画画额度")
    assert "tools" in infer_tool_domains("有什么工具可以用")
    assert infer_tool_domains("今天天气不错") == frozenset()


def test_parse_decl_keeps_hints_and_visibility() -> None:
    from pallas.product.llm.tools.declare import llm_command_tool_row
    from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl

    decl = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="demo.x",
            command_id="demo.x",
            description="demo",
            parameters={"type": "object", "properties": {}},
            command_template="demo",
            hints=["音乐", "放歌"],
            visibility="deferred",
        )
    )
    assert decl is not None
    assert decl.hints == ["音乐", "放歌"]
    assert decl.visibility == "deferred"
