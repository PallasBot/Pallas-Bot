from __future__ import annotations

from pallas.product.llm.tools.patterns import domains_from_structure

from pallas.product.llm.tools.select import infer_tool_domains, preferred_tool_names


def test_structure_recall_sing_compact_forms() -> None:
    assert "sing" in domains_from_structure("放首铁花飞")
    assert "sing" in domains_from_structure("我叫你放首铁花飞")
    assert "sing" in domains_from_structure("来首晴天")
    assert "sing" in domains_from_structure("播一下歌")


def test_structure_recall_other_domains() -> None:
    assert "drink" in domains_from_structure("来杯酒")
    assert "draw" in domains_from_structure("来张图")
    assert "draw" in domains_from_structure("牛牛画个猫")
    assert "roulette" in domains_from_structure("来一把轮盘")
    assert "help" in domains_from_structure("怎么用牛牛")
    assert "memes" in domains_from_structure("做个摸表情")
    # 点名祈使：不依赖具体模板名
    assert "memes" in domains_from_structure("牛牛做个流萤举牌")
    assert "memes" in domains_from_structure("牛牛来个摸")
    assert "memes" not in domains_from_structure("来个虹夏举牌")  # 未点名且无「表情」字


def test_infer_domains_includes_structure_without_keyword_lexicon() -> None:
    # 「放首X」不在旧关键词表里的整词，靠结构召回
    domains = infer_tool_domains("放首铁花飞")
    assert "sing" in domains


def test_preferred_tool_names_choose_song_request_for_playback_verbs() -> None:
    assert preferred_tool_names("牛牛放一首铁花飞") == frozenset({"sing.request_song"})
    assert preferred_tool_names("牛牛播一下晴天") == frozenset({"sing.request_song"})
    assert preferred_tool_names("牛牛唱一首铁花飞") == frozenset({"sing.sing"})


def test_infer_domains_memory_keywords() -> None:
    domains = infer_tool_domains("你还记得以前说过的事吗")
    assert "memory" in domains
