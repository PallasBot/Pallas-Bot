"""输出后处理：舞台括号旁白与截断句。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.output_filter import (
    looks_like_truncated_reply,
    resolve_output_filtered_reply,
    strip_stage_direction_parens,
)


def test_strip_stage_direction_parens() -> None:
    assert strip_stage_direction_parens("（叹气）我真牛啊") == "我真牛啊"
    assert strip_stage_direction_parens("没想吓你啊（笑）") == "没想吓你啊"
    assert strip_stage_direction_parens("（轻笑一声）帽子扣得勤") == "帽子扣得勤"
    assert strip_stage_direction_parens("（装傻）等你再说") == "等你再说"
    # 人名注解应保留
    assert "维尼修斯" in strip_stage_direction_parens("小熊（维尼修斯）也猛")


def test_strip_stage_direction_parens_broadened() -> None:
    assert strip_stage_direction_parens("（翻个白眼）我走了，你继续喵吧。") == "我走了，你继续喵吧。"
    assert strip_stage_direction_parens("（引用）你这话说的，啥意思啊") == "你这话说的，啥意思啊"
    # 行首整段旁白兜底剥离，再拆段
    assert strip_stage_direction_parens("（这谁点的歌啊）\nStan？ 还是Eminem的Stan？") == "Stan？ 还是Eminem的Stan？"
    assert strip_stage_direction_parens("（抬头看看）\n这得先定义什么叫正常") == "这得先定义什么叫正常"


def test_looks_like_truncated_reply() -> None:
    assert looks_like_truncated_reply("我真牛啊，把别的")
    assert looks_like_truncated_reply("行，我把自己打成")
    assert not looks_like_truncated_reply("在的，咋了")
    assert not looks_like_truncated_reply("嗯？")


def test_resolve_strips_stage_and_blocks_truncation() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "（叹气）我真牛啊，把别的") == ""
    assert resolve_output_filtered_reply(task, "（笑）在的，咋了") == "在的，咋了"


def test_resolve_blocks_hmm_filler() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "嗯？") == ""
    assert resolve_output_filtered_reply(task, "嗯") == ""
    assert resolve_output_filtered_reply(task, "啊？") == ""
