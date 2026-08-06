"""self aliases 拆分通称与专属，并支持复合昵称短别名。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.persona.self_identity import (
    extract_exclusive_self_aliases,
    extract_generic_self_aliases,
    extract_self_aliases,
    merge_self_aliases,
    shorten_niu_niu_compound_alias,
)


def test_shorten_doubao_niu_niu() -> None:
    assert shorten_niu_niu_compound_alias("豆包牛牛") == "豆包"
    assert shorten_niu_niu_compound_alias("牛牛测试机") == "测试机"
    assert shorten_niu_niu_compound_alias("牛牛") is None


def test_extract_includes_short_from_login() -> None:
    aliases = extract_self_aliases(None, login_nickname="豆包牛牛")
    assert "豆包牛牛" in aliases
    assert "豆包" in aliases
    assert "牛牛" in aliases


def test_extract_includes_managed_display_name_alongside_login_nickname() -> None:
    aliases = extract_self_aliases(
        None,
        login_nickname="QQ 原昵称",
        managed_display_name="漂亮牛牛",
    )

    assert aliases[:2] == ["漂亮牛牛", "漂亮"]
    assert "QQ 原昵称" in aliases
    assert "牛牛" in aliases


def test_exclusive_vs_generic_split() -> None:
    exclusives = extract_exclusive_self_aliases(None, login_nickname="豆包牛牛")
    generics = extract_generic_self_aliases()
    assert "豆包牛牛" in exclusives
    assert "豆包" in exclusives
    assert "牛牛" not in exclusives
    assert generics == ["牛牛"]


def test_extract_exclusive_includes_managed_display_name() -> None:
    aliases = extract_exclusive_self_aliases(
        None,
        login_nickname="QQ 原昵称",
        managed_display_name="漂亮牛牛",
    )

    assert aliases[:2] == ["漂亮牛牛", "漂亮"]
    assert "QQ 原昵称" in aliases


@pytest.mark.asyncio
async def test_merge_self_aliases_keeps_learned_exclusive_when_filtering_generics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[tuple[int, str, dict]] = []
    remembered: list[tuple[int, list[str]]] = []

    class DummyRepo:
        async def get(self, _bot_id: int):
            return SimpleNamespace(persona={"self_aliases": []})

        async def upsert_field(self, bot_id: int, field: str, value: dict) -> None:
            written.append((bot_id, field, value))

    monkeypatch.setattr("pallas.product.persona.self_identity.make_bot_config_repository", lambda: DummyRepo())
    monkeypatch.setattr(
        "pallas.core.platform.ingress.alias_route.remember_learned_self_aliases",
        lambda bot_id, aliases: remembered.append((bot_id, aliases)),
    )

    ok = await merge_self_aliases(42, ["帕拉斯"])

    assert ok is True
    assert written == [(42, "persona", {"self_aliases": ["帕拉斯"]})]
    assert remembered == [(42, ["帕拉斯"])]


@pytest.mark.asyncio
async def test_merge_self_aliases_does_not_persist_derived_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[tuple[int, str, dict]] = []
    remembered: list[tuple[int, list[str]]] = []

    class DummyRepo:
        async def get(self, _bot_id: int):
            return SimpleNamespace(persona={"self_aliases": ["豆包牛牛"]})

        async def upsert_field(self, bot_id: int, field: str, value: dict) -> None:
            written.append((bot_id, field, value))

    monkeypatch.setattr("pallas.product.persona.self_identity.make_bot_config_repository", lambda: DummyRepo())
    monkeypatch.setattr(
        "pallas.core.platform.ingress.alias_route.remember_learned_self_aliases",
        lambda bot_id, aliases: remembered.append((bot_id, aliases)),
    )

    ok = await merge_self_aliases(42, ["阿帕"])

    assert ok is True
    assert written == [(42, "persona", {"self_aliases": ["豆包牛牛", "阿帕"]})]
    assert remembered == [(42, ["豆包牛牛", "阿帕"])]
