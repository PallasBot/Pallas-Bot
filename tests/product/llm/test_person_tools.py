"""人物档案工具：person.profile.query 携带稳定偏好事实。"""

from __future__ import annotations

import pytest

from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.person import handle_person_profile_query

BOT_ID = 101
GROUP_ID = 777
USER_ID = 100


def make_context() -> ToolInvokeContext:
    return ToolInvokeContext(bot_id=BOT_ID, group_id=GROUP_ID, user_id=USER_ID, request_id="req-1")


class _FakeProfile:
    def model_dump(self, *, mode):  # noqa: ARG002
        return {"facts": ["称呼：阿猫"], "affinity": 0.2}


@pytest.mark.asyncio
async def test_query_returns_person_facts_alongside_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pallas.product.llm.memory.person_facts._store_path", lambda: tmp_path / "person_facts.json")
    from pallas.product.llm.memory.person_facts import save_person_fact

    save_person_fact(
        bot_id=BOT_ID, group_id=GROUP_ID, user_id=USER_ID, content="常用表情包：猫猫", source="sticker_habit"
    )

    async def fake_profile(bot_id, group_id, user_id):
        return _FakeProfile()

    monkeypatch.setattr("pallas.product.llm.tools.person.retrieve_relationship_profile", fake_profile)

    result = await handle_person_profile_query({"user_id": USER_ID}, make_context())

    assert result["ok"] is True
    assert result["result"]["facts"] == ["常用表情包：猫猫"]
    assert result["result"]["profile"]["affinity"] == 0.2


@pytest.mark.asyncio
async def test_query_returns_facts_without_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pallas.product.llm.memory.person_facts._store_path", lambda: tmp_path / "person_facts.json")

    async def fake_profile(bot_id, group_id, user_id):
        return None

    monkeypatch.setattr("pallas.product.llm.tools.person.retrieve_relationship_profile", fake_profile)

    result = await handle_person_profile_query({"user_id": USER_ID}, make_context())

    assert result == {"ok": True, "result": {"user_id": USER_ID, "facts": []}}
