from packages.help.help_args import (
    PLUGIN_DISABLE_ALL_COMMAND,
    PLUGIN_DISABLE_COMMAND,
    PLUGIN_ENABLE_ALL_COMMAND,
    PLUGIN_ENABLE_COMMAND,
    extract_help_tail,
    parse_help_args,
    parse_plugin_toggle_args,
)
from pallas.core.foundation.command_prefix import matches_command_prefix


def matches_toggle_prefix(
    plaintext: str,
    command: str,
    *,
    exclude_prefixes: tuple[str, ...] = (),
) -> bool:
    text = plaintext or ""
    for excluded in exclude_prefixes:
        if matches_command_prefix(text, excluded):
            return False
    return matches_command_prefix(text, command)


def test_extract_help_tail_strips_slash_prefix() -> None:
    assert extract_help_tail("/牛牛帮助 1") == "1"
    assert extract_help_tail("牛牛帮助MAA远控") == "MAA远控"


def test_parse_spaced_args() -> None:
    assert parse_help_args("牛牛帮助 1", plugin_count=10) == ["1"]
    assert parse_help_args("牛牛帮助 1 2", plugin_count=10) == ["1", "2"]
    assert parse_help_args("牛牛帮助 MAA远控", plugin_count=10) == ["MAA远控"]


def test_parse_compact_plugin_index() -> None:
    assert parse_help_args("牛牛帮助1", plugin_count=10) == ["1"]
    assert parse_help_args("/牛牛帮助3", plugin_count=10) == ["3"]


def test_parse_compact_plugin_index_when_many_plugins() -> None:
    assert parse_help_args("牛牛帮助12", plugin_count=17) == ["12"]


def test_parse_compact_plugin_and_function_index() -> None:
    assert parse_help_args("牛牛帮助12", plugin_count=5) == ["1", "2"]
    assert parse_help_args("牛牛帮助12", plugin_count=1) == ["1", "2"]


def test_parse_compact_plugin_name_without_space() -> None:
    assert parse_help_args("牛牛帮助MAA远控", plugin_count=10) == ["MAA远控"]
    assert parse_help_args("牛牛帮助maa远控", plugin_count=10) == ["maa远控"]


def test_matches_help_command_prefix_case_insensitive() -> None:
    assert matches_command_prefix("牛牛帮助", "牛牛帮助")
    assert matches_command_prefix("/牛牛帮助", "牛牛帮助")
    assert matches_command_prefix("牛牛帮助 1", "牛牛帮助")
    assert not matches_command_prefix("牛牛开启", "牛牛帮助")


def test_extract_help_tail_preserves_arg_casing() -> None:
    assert extract_help_tail("牛牛帮助 MAA远控") == "MAA远控"
    assert extract_help_tail("牛牛帮助 maa远控") == "maa远控"


def test_parse_compact_plugin_index_and_function_name() -> None:
    assert parse_help_args("牛牛帮助1复读", plugin_count=10) == ["1", "复读"]


def test_parse_empty_is_home() -> None:
    assert parse_help_args("牛牛帮助", plugin_count=10) == []
    assert parse_help_args("  牛牛帮助  ", plugin_count=10) == []


def test_parse_toggle_compact_plugin_index() -> None:
    assert parse_plugin_toggle_args("牛牛开启1", PLUGIN_ENABLE_COMMAND, plugin_count=10) == ["1"]
    assert parse_plugin_toggle_args("牛牛关闭MAA远控", PLUGIN_DISABLE_COMMAND, plugin_count=10) == ["MAA远控"]


def test_parse_toggle_does_not_split_plugin_and_function_digits() -> None:
    assert parse_plugin_toggle_args("牛牛开启12", PLUGIN_ENABLE_COMMAND, plugin_count=5) == ["12"]
    assert parse_plugin_toggle_args("牛牛关闭12", PLUGIN_DISABLE_COMMAND, plugin_count=17) == ["12"]


def test_parse_toggle_compact_with_global_suffix() -> None:
    assert parse_plugin_toggle_args("牛牛开启1global", PLUGIN_ENABLE_COMMAND, plugin_count=10) == [
        "1",
        "global",
    ]
    assert parse_plugin_toggle_args("牛牛关闭 1 global", PLUGIN_DISABLE_COMMAND, plugin_count=10) == [
        "1",
        "global",
    ]


def test_toggle_all_commands_do_not_match_single_toggle_prefix() -> None:
    assert matches_toggle_prefix("牛牛开启全部功能", PLUGIN_ENABLE_ALL_COMMAND)
    assert not matches_toggle_prefix(
        "牛牛开启全部功能",
        PLUGIN_ENABLE_COMMAND,
        exclude_prefixes=(PLUGIN_ENABLE_ALL_COMMAND,),
    )
    assert matches_toggle_prefix("牛牛开启 复读", PLUGIN_ENABLE_COMMAND, exclude_prefixes=(PLUGIN_ENABLE_ALL_COMMAND,))
    assert matches_toggle_prefix("牛牛关闭全部功能", PLUGIN_DISABLE_ALL_COMMAND)
    assert not matches_toggle_prefix(
        "牛牛关闭全部功能",
        PLUGIN_DISABLE_COMMAND,
        exclude_prefixes=(PLUGIN_DISABLE_ALL_COMMAND,),
    )
