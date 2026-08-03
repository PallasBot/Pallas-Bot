"""软召回：硬域未命中时按 hints/描述装配少量候选，缺参先追问。"""

from __future__ import annotations

from pallas.product.llm.task_metrics import clear_llm_task_metrics_for_tests, llm_task_metrics_snapshot
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl
from pallas.product.llm.tools.plugin_bootstrap import build_command_tool_spec
from pallas.product.llm.tools.registry import (
    clear_tool_registry,
    register_tool,
    tool_catalog_for_chat,
    tool_metadata_for_chat,
)
from pallas.product.llm.tools.select import infer_tool_domains
from pallas.product.llm.tools.soft_recall import (
    SoftRecallHit,
    missing_required_params_for_text,
    select_soft_recall_hits,
)


def _cfg(**overrides):
    base = {
        "llm_tools_enabled": True,
        "llm_tools_selective": True,
        "llm_tools_soft_recall_enabled": True,
        "llm_tools_soft_recall_min_score": 6,
        "llm_tools_soft_recall_max_candidates": 3,
        "llm_tools_blacklist": [],
        "llm_tools_desc_max_len": 200,
    }
    base.update(overrides)
    return type("Cfg", (), base)()


def _register_song_and_duel() -> None:
    clear_tool_registry()
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="sing.request_song",
                    command_id="sing.request_song",
                    description="点歌",
                    parameters={
                        "type": "object",
                        "properties": {"song": {"type": "string"}},
                        "required": ["song"],
                    },
                    command_template="牛牛点歌 {song}",
                    hints=["点歌", "放首歌", "音乐", "我想听", "想听", "听一下", "来点音乐"],
                )
            ),
            plugin_name="sing",
            plugin_title="唱歌",
        )
    )
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="duel.cage",
                    command_id="duel.cage",
                    description="决斗",
                    parameters={"type": "object", "properties": {}},
                    command_template="牛牛决斗",
                    hints=["决斗", "想打一架"],
                )
            ),
            plugin_name="duel",
            plugin_title="决斗",
        )
    )


def test_soft_recall_hit_for_want_listen(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_llm_task_metrics_for_tests()
    _register_song_and_duel()

    assert infer_tool_domains("我想听") == frozenset()
    catalog = tool_catalog_for_chat(task="llm_chat", user_text="我想听")
    assert catalog is not None
    assert catalog.selection.selection_source == "soft_recall"
    assert catalog.selection.ask_before_call is True
    assert [item.name for item in catalog.tools] == ["sing.request_song"]
    assert "song" in (catalog.selection.missing_required_params.get("sing.request_song") or [])

    meta = tool_metadata_for_chat(task="llm_chat", user_text="我想听")
    assert meta.get("tools_enabled") is True
    assert meta.get("selection_source") == "soft_recall"
    assert meta.get("ask_before_call") is True
    assert meta.get("tool_choice_prefer") != "required"
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["soft_recall_hit"] == 1
    clear_llm_task_metrics_for_tests()


def test_soft_recall_with_song_residual_not_ask(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_song_and_duel()
    catalog = tool_catalog_for_chat(task="llm_chat", user_text="我想听铁花飞")
    assert catalog is not None
    assert catalog.selection.selection_source == "soft_recall"
    assert catalog.selection.ask_before_call is False
    assert missing_required_params_for_text(_song_spec(), "我想听铁花飞") == ()
    meta = tool_metadata_for_chat(task="llm_chat", user_text="我想听铁花飞")
    # 软召回材料齐全时与硬域一样强制调工具，避免空口答应
    assert meta.get("tool_choice_prefer") == "required"


def test_imperative_stem_bonus_addressed(monkeypatch) -> None:
    from pallas.product.llm.tools.score import score_tool_text

    score = score_tool_text(
        "牛牛做个流萤举牌",
        name="memes.recommend",
        description="推荐并制作表情",
        hints=frozenset({"做个表情", "牛牛做个", "表情包"}),
    )
    assert score >= 6


def _song_spec():
    return build_command_tool_spec(
        parse_llm_command_tool_decl(
            llm_command_tool_row(
                name="sing.request_song",
                command_id="sing.request_song",
                description="点歌",
                parameters={
                    "type": "object",
                    "properties": {"song": {"type": "string"}},
                    "required": ["song"],
                },
                command_template="牛牛点歌 {song}",
                hints=["点歌", "我想听", "想听"],
            )
        ),
        plugin_name="sing",
        plugin_title="唱歌",
    )


def test_soft_recall_idle_chat_empty(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_llm_task_metrics_for_tests()
    _register_song_and_duel()
    assert tool_catalog_for_chat(task="llm_chat", user_text="今天天气不错") is None
    assert tool_metadata_for_chat(task="llm_chat", user_text="今天天气不错") == {}
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["selective_empty"] == 1
    assert snap["by_task"]["llm_chat"]["soft_recall_empty"] == 1
    clear_llm_task_metrics_for_tests()


def test_selective_hard_command_still_preferred(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_song_and_duel()
    catalog = tool_catalog_for_chat(task="llm_chat", user_text="放首歌，铁花飞")
    assert catalog is not None
    assert catalog.selection.selection_source == "selective"
    assert "sing" in catalog.selection.inferred_domains
    names = {item.name for item in catalog.tools}
    assert "sing.request_song" in names
    assert "duel.cage" not in names


def test_soft_recall_does_not_expand_to_unrelated_tools(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_song_and_duel()
    hits = select_soft_recall_hits("我想听")
    assert [hit.spec.name for hit in hits] == ["sing.request_song"]


def test_help_hard_domain_for_casual_phrase() -> None:
    assert "help" in infer_tool_domains("有啥功能")
    assert "help" in infer_tool_domains("@有啥功能".replace("@", ""))


def test_semantic_recall_falls_back_to_the_best_domain_candidate(monkeypatch) -> None:
    from pallas.product.llm.tools import registry

    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_song_and_duel()
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="sing.sing",
                    command_id="sing.sing",
                    description="AI 翻唱指定歌曲。",
                    parameters={"type": "object", "properties": {"song": {"type": "string"}}},
                    command_template="牛牛唱歌 {song}",
                    hints=["唱歌", "翻唱"],
                )
            ),
            plugin_name="sing",
            plugin_title="唱歌",
        )
    )
    request_song = next(spec for spec in registry.list_registered_tools() if spec.name == "sing.request_song")
    monkeypatch.setattr(
        "pallas.product.llm.tools.semantic_recall.select_semantic_recall_hits",
        lambda *_args, **_kwargs: [SoftRecallHit(spec=request_song, score=88, missing_required=())],
    )

    catalog = tool_catalog_for_chat(task="llm_chat", user_text="牛牛播一下这首歌")

    assert catalog is not None
    assert [item.name for item in catalog.tools] == ["sing.request_song"]
    assert catalog.selection.selection_source == "selective+semantic"
    assert catalog.selection.semantic_recall_candidates == [{"name": "sing.request_song", "score": 88}]
