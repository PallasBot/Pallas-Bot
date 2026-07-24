"""记忆图谱 scope / 序列化单测（不依赖真实 DB）。"""

from pallas.product.llm.memory.graph.scope import make_scope_key, parse_scope_key, resolve_scope


def test_make_and_parse_scope_key() -> None:
    sk = make_scope_key(bot_id=12345, group_id=678)
    assert sk == "bot:12345:group:678"
    bot, group = parse_scope_key(sk)
    assert bot == 12345
    assert group == 678


def test_resolve_scope_from_bot_group() -> None:
    sk, bot, group = resolve_scope(bot_id=1, group_id=None)
    assert sk == "bot:1:group:0"
    assert bot == 1
    assert group == 0


def test_resolve_scope_from_key() -> None:
    sk, bot, group = resolve_scope(scope_key="bot:9:group:3")
    assert sk == "bot:9:group:3"
    assert bot == 9
    assert group == 3


def test_resolve_scope_rejects_bad_key() -> None:
    try:
        resolve_scope(scope_key="group:1")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
