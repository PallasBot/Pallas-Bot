from types import SimpleNamespace

from packages.help.plugin_match import find_matching_plugins, normalize_help_key, plugin_match_score


def _plugin(name: str, display: str, *, extra_aliases: list[str] | None = None):
    extra = {"help_aliases": extra_aliases} if extra_aliases else {}
    return SimpleNamespace(
        name=name,
        metadata=SimpleNamespace(name=display, extra=extra),
    )


def test_normalize_help_key_strips_spaces_and_case():
    assert normalize_help_key("  MAA 远控 ") == "maa远控"
    assert normalize_help_key("MAA远控") == "maa远控"


def test_maa_matches_display_name_without_space():
    p = _plugin("maa", "MAA 远控")
    assert plugin_match_score(p, "MAA远控") == 100
    assert find_matching_plugins("远控", [p]) == [p]


def test_alias_table():
    p = _plugin("repeater", "牛牛复读")
    assert find_matching_plugins("复读", [p]) == [p]


def test_ambiguous_substring():
    a = _plugin("drink", "牛牛喝酒")
    b = _plugin("chat", "酒后聊天")
    matches = find_matching_plugins("酒", [a, b])
    assert len(matches) >= 2


def test_casual_chat_vs_drunk_chat():
    llm = _plugin("llm_chat", "智能对话", extra_aliases=["牛牛聊天", "随时闲聊", "酒后聊天"])
    pool = [llm]
    assert find_matching_plugins("智能对话", pool) == [llm]
    assert find_matching_plugins("随时闲聊", pool) == [llm]
    assert find_matching_plugins("酒后聊天", pool) == [llm]
    assert find_matching_plugins("牛牛聊天", pool) == [llm]
