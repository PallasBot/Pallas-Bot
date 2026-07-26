"""同伴牛牛 persona 注入与教导句式。"""

from __future__ import annotations

from pallas.product.persona.peer_bots_prompt import (
    compile_peer_bots_prompt,
    is_peer_harm_expression,
    parse_peer_alias_teach,
)


def test_compile_peer_bots_prompt_lists_peers() -> None:
    prompt = compile_peer_bots_prompt(
        self_bot_id=1001,
        peer_labels=["牛BOT", "测试机"],
        taught_aliases=["漂亮牛"],
    )
    assert "【同伴牛牛】" in prompt
    assert "牛BOT" in prompt
    assert "测试机" in prompt
    assert "漂亮牛" in prompt
    assert "不是外人" in prompt or "同伴" in prompt


def test_compile_peer_bots_prompt_empty_without_peers() -> None:
    assert compile_peer_bots_prompt(self_bot_id=1001, peer_labels=[], taught_aliases=[]) == ""


def test_parse_peer_alias_teach() -> None:
    assert parse_peer_alias_teach("记住：测试机也是牛牛") == ["测试机"]
    assert parse_peer_alias_teach("漂亮牛是同伴") == ["漂亮牛"]
    assert parse_peer_alias_teach("记住 xxx是同伴牛牛") == ["xxx"]
    assert parse_peer_alias_teach("今天吃什么") == []
    assert parse_peer_alias_teach("牛牛就是我") == []


def test_is_peer_harm_expression() -> None:
    assert is_peer_harm_expression("坦诚承认是你打了其他牛牛，还不够狠？")
    assert is_peer_harm_expression("好好好，都是我打的，没留活口那种。")
    assert is_peer_harm_expression("哪只都不舍得打死")
    assert not is_peer_harm_expression("另一只牛牛在说话")
    assert not is_peer_harm_expression("在的，咋了")
