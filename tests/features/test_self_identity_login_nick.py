"""登录昵称注入自称 aliases：优先于默认「牛牛」，且与之并存。"""

from __future__ import annotations

from pallas.product.persona.self_identity import (
    compile_repeater_self_identity_prompt,
    compile_self_identity_prompt,
    extract_self_aliases,
)


def test_extract_self_aliases_login_nickname_primary_keeps_niu_niu() -> None:
    aliases = extract_self_aliases(None, login_nickname="小牛")
    assert aliases[0] == "小牛"
    assert "牛牛" in aliases
    assert "帕拉斯" in aliases


def test_extract_self_aliases_without_login_keeps_default_primary() -> None:
    aliases = extract_self_aliases(None)
    assert aliases[0] == "牛牛"


def test_extract_self_aliases_login_dedupes_default() -> None:
    aliases = extract_self_aliases(None, login_nickname="牛牛")
    assert aliases[0] == "牛牛"
    assert aliases.count("牛牛") == 1


def test_extract_self_aliases_merges_learned_after_defaults() -> None:
    aliases = extract_self_aliases({"self_aliases": ["阿帕"]}, login_nickname="小牛")
    assert aliases[0] == "小牛"
    assert "牛牛" in aliases
    assert "阿帕" in aliases
    assert aliases.index("小牛") < aliases.index("牛牛") < aliases.index("阿帕")


def test_compile_self_identity_prompt_uses_login_as_primary() -> None:
    prompt = compile_self_identity_prompt(login_nickname="小牛")
    assert "「小牛」" in prompt
    assert "牛牛" in prompt


def test_compile_repeater_self_identity_prompt_uses_login_as_primary() -> None:
    prompt = compile_repeater_self_identity_prompt(login_nickname="小牛")
    assert "「小牛」" in prompt
    assert "牛牛" in prompt or "等" in prompt
