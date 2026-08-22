from __future__ import annotations

import pytest

from pallas.product.persona import style_governance as governance


class DummyGroupRepo:
    def __init__(self) -> None:
        self.upserts: list[tuple[int, str, object]] = []

    async def get(self, key_id: int, *, ignore_cache: bool = False):
        return None

    async def upsert_field(self, key_id: int, field: str, value):
        self.upserts.append((key_id, field, value))


@pytest.fixture
def governance_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    repo = DummyGroupRepo()
    invalidated: list[int | None] = []
    monkeypatch.setattr(governance, "group_style_governance_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(governance, "make_group_config_repository", lambda: repo)
    monkeypatch.setattr(
        governance,
        "invalidate_persona_cache",
        lambda bot_id=None: invalidated.append(bot_id),
    )
    return governance, repo, invalidated


@pytest.mark.asyncio
async def test_clear_group_style_pauses_group_collection_and_scoped_injection(governance_env) -> None:
    _governance, repo, invalidated = governance_env
    assert governance.group_style_status(bot_id=1, group_id=2) == {
        "collection_enabled": True,
        "injection_enabled": True,
    }
    result = await governance.clear_group_style(group_id=2, continue_learning=False)
    assert result["collection_enabled"] is False
    assert result["injection_enabled"] is False
    assert governance.group_style_status(bot_id=1, group_id=2)["injection_enabled"] is False
    assert governance.group_style_status(bot_id=1, group_id=3)["collection_enabled"] is True
    assert repo.upserts == [(2, "style_profile", None)]
    assert invalidated == [None]


@pytest.mark.asyncio
async def test_default_status_is_enabled(governance_env) -> None:
    _governance, _repo, _invalidated = governance_env
    assert governance.group_style_status(bot_id=42, group_id=7) == {
        "collection_enabled": True,
        "injection_enabled": True,
    }


@pytest.mark.asyncio
async def test_set_group_style_collection_is_group_scoped(governance_env) -> None:
    _governance, _repo, _invalidated = governance_env
    result = await governance.set_group_style_collection(group_id=2, enabled=False)
    assert result["collection_enabled"] is False
    assert governance.group_style_status(bot_id=1, group_id=2)["collection_enabled"] is False
    assert governance.group_style_status(bot_id=9, group_id=2)["collection_enabled"] is False
    assert governance.group_style_status(bot_id=1, group_id=3)["collection_enabled"] is True


@pytest.mark.asyncio
async def test_set_group_style_injection_is_bot_and_group_scoped(governance_env) -> None:
    _governance, _repo, _invalidated = governance_env
    result = await governance.set_group_style_injection(bot_id=1, group_id=2, enabled=False)
    assert result["injection_enabled"] is False
    assert result["collection_enabled"] is True
    assert governance.group_style_status(bot_id=1, group_id=2)["injection_enabled"] is False
    assert governance.group_style_status(bot_id=2, group_id=2)["injection_enabled"] is True
    assert governance.group_style_status(bot_id=1, group_id=3)["injection_enabled"] is True


@pytest.mark.asyncio
async def test_set_group_style_injection_invalidates_bot_persona_cache(governance_env) -> None:
    _governance, _repo, invalidated = governance_env
    await governance.set_group_style_injection(bot_id=1, group_id=2, enabled=False)
    await governance.set_group_style_injection(bot_id=9, group_id=2, enabled=True)
    assert invalidated == [1, 9]


@pytest.mark.asyncio
async def test_clear_group_style_with_continue_learning_re_enables_collection(governance_env) -> None:
    _governance, repo, _invalidated = governance_env
    await governance.set_group_style_collection(group_id=2, enabled=False)
    await governance.set_group_style_injection(bot_id=1, group_id=2, enabled=False)

    result = await governance.clear_group_style(group_id=2, continue_learning=True)

    assert result["collection_enabled"] is True
    assert governance.group_style_status(bot_id=1, group_id=2)["collection_enabled"] is True
    assert governance.group_style_status(bot_id=1, group_id=2)["injection_enabled"] is False
    assert repo.upserts == [(2, "style_profile", None)]


@pytest.mark.asyncio
async def test_clear_group_style_full_pause_overrides_bot_injection(governance_env) -> None:
    _governance, _repo, _invalidated = governance_env
    await governance.set_group_style_injection(bot_id=1, group_id=2, enabled=True)

    result = await governance.clear_group_style(group_id=2, continue_learning=False)

    assert result["injection_enabled"] is False
    assert governance.group_style_status(bot_id=1, group_id=2)["injection_enabled"] is False
    assert governance.group_style_status(bot_id=3, group_id=2)["injection_enabled"] is False
    assert governance.group_style_status(bot_id=1, group_id=3)["injection_enabled"] is True
