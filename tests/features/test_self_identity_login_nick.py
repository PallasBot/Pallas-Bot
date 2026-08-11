"""登录昵称注入自称 aliases：优先于默认「牛牛」，且与之并存。"""

from __future__ import annotations

from pallas.product.persona.self_identity import (
    DEFAULT_GENERIC_ALIASES,
    compile_repeater_self_identity_prompt,
    compile_self_identity_prompt,
    extract_self_aliases,
)


def test_extract_self_aliases_login_nickname_primary_keeps_niu_niu() -> None:
    aliases = extract_self_aliases(None, login_nickname="小牛")
    assert aliases[0] == "小牛"
    assert "牛牛" in aliases


def test_default_generic_aliases_are_niu_niu_only() -> None:
    assert DEFAULT_GENERIC_ALIASES == ("牛牛",)
    aliases = extract_self_aliases(None)
    assert aliases[0] == "牛牛"
    assert "帕拉斯" not in aliases
    assert "Pallas" not in aliases


def test_login_pallas_keeps_exclusive_pallas() -> None:
    aliases = extract_self_aliases(None, login_nickname="帕拉斯")
    assert "帕拉斯" in aliases
    assert "牛牛" in aliases


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
    assert aliases.index("小牛") < aliases.index("阿帕") < aliases.index("牛牛")


def test_compile_self_identity_prompt_keeps_login_nickname_out_of_role_context() -> None:
    prompt = compile_self_identity_prompt(login_nickname="小牛")
    assert "牛牛" in prompt
    assert "小牛" not in prompt


def test_compile_self_identity_prompt_keeps_learned_aliases_out_of_role_context() -> None:
    prompt = compile_self_identity_prompt(
        {"self_aliases": ["啥阴", "阿帕"]},
        login_nickname="小牛",
    )

    assert "只用于判断是否在叫你" in prompt
    assert "啥阴" not in prompt
    assert "阿帕" not in prompt


def test_compile_repeater_self_identity_prompt_keeps_login_nickname_out_of_role_context() -> None:
    prompt = compile_repeater_self_identity_prompt(login_nickname="小牛")
    assert "牛牛" in prompt
    assert "登录昵称和学习别名只供路由判断" in prompt
    assert "小牛" not in prompt


def test_compile_repeater_self_identity_prompt_uses_generic_text_without_exclusive(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.extract_generic_self_aliases",
        lambda: ["测试牛"],
    )
    prompt = compile_repeater_self_identity_prompt()
    assert "测试牛" in prompt
    assert "牛牛" not in prompt
