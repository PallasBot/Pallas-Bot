"""群内社交工具：主人/成员查询与受控提及令牌。"""

from __future__ import annotations

import asyncio

from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.select import infer_tool_domains
from pallas.product.llm.tools.social import (
    clear_social_mention_state,
    grant_mention,
    handle_master_info,
    handle_member_find,
    is_social_request,
    parse_superuser_ids,
    replace_mention_tokens,
    resolve_mention_qq,
)

MASTER_QQ = 3023094357
BOT_ID = 10001
GROUP_ID = 20002
REQUEST_ID = "request-1"


class FakeBot:
    def __init__(self, members):
        self.members = members

    async def get_group_member_info(self, group_id, user_id):
        for member in self.members:
            if member["user_id"] == user_id:
                return dict(member)
        raise RuntimeError("member not found")

    async def get_group_member_list(self, group_id):
        return list(self.members)


def make_context() -> ToolInvokeContext:
    return ToolInvokeContext(bot_id=BOT_ID, group_id=GROUP_ID, user_id=9999, request_id=REQUEST_ID)


def install_bot(monkeypatch, members):
    async def fake_bot_for(bot_id):
        return FakeBot(members)

    async def fake_resolve_masters(bot_id):
        return [MASTER_QQ]

    monkeypatch.setattr("pallas.product.llm.tools.social._bot_for", fake_bot_for)
    monkeypatch.setattr(
        "pallas.product.llm.tools.social.parse_superuser_ids",
        lambda: [MASTER_QQ],
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.social.resolve_master_user_ids",
        fake_resolve_masters,
    )


def test_parse_superuser_ids_json_list(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.social.repo_env_raw_value",
        lambda key: '["3023094357", "12345"]',
    )
    assert parse_superuser_ids() == [3023094357, 12345]


def test_parse_superuser_ids_comma_separated(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.social.repo_env_raw_value",
        lambda key: "3023094357, 12345",
    )
    assert parse_superuser_ids() == [3023094357, 12345]


def test_parse_superuser_ids_empty(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.tools.social.repo_env_raw_value", lambda key: "")
    assert parse_superuser_ids() == []


def test_master_in_group(monkeypatch) -> None:
    clear_social_mention_state()
    install_bot(monkeypatch, [{"user_id": MASTER_QQ, "nickname": "老板", "card": ""}])
    result = asyncio.run(handle_master_info({}, make_context()))
    assert result["ok"] is True
    payload = result["result"]
    assert payload["master_in_group"] is True
    assert len(payload["masters"]) == 1
    assert payload["masters"][0]["name"] == "老板"
    assert "qq" not in payload["masters"][0]
    assert resolve_mention_qq(BOT_ID, GROUP_ID, REQUEST_ID, payload["masters"][0]["key"]) == MASTER_QQ


def test_master_not_in_group_keeps_privacy(monkeypatch) -> None:
    clear_social_mention_state()
    install_bot(monkeypatch, [{"user_id": 8888, "nickname": "路人", "card": ""}])
    result = asyncio.run(handle_master_info({}, make_context()))
    assert result["ok"] is True
    payload = result["result"]
    assert payload["master_in_group"] is False
    assert payload["masters"] == []
    raw = str(result)
    assert "3023094357" not in raw


def test_member_find_matches_by_card(monkeypatch) -> None:
    clear_social_mention_state()
    members = [
        {"user_id": 1111, "nickname": "小明", "card": "泰坦"},
        {"user_id": 2222, "nickname": "小红", "card": ""},
    ]
    install_bot(monkeypatch, members)
    result = asyncio.run(handle_member_find({"query": "泰坦"}, make_context()))
    assert result["ok"] is True
    matches = result["result"]["matches"]
    assert len(matches) == 1
    assert matches[0]["name"] == "泰坦"
    assert "qq" not in matches[0]
    assert resolve_mention_qq(BOT_ID, GROUP_ID, REQUEST_ID, matches[0]["key"]) == 1111


def test_member_name_cannot_override_reserved_token(monkeypatch) -> None:
    clear_social_mention_state()
    install_bot(monkeypatch, [{"user_id": 1111, "nickname": "", "card": "master_0"}])
    result = asyncio.run(handle_member_find({"query": "master_0"}, make_context()))
    assert result["ok"] is True
    assert resolve_mention_qq(BOT_ID, GROUP_ID, REQUEST_ID, "member_0") == 1111
    assert resolve_mention_qq(BOT_ID, GROUP_ID, REQUEST_ID, "master_0") is None


def test_member_display_name_strips_cq_and_token_syntax() -> None:
    from pallas.product.llm.tools.social import _member_display_name

    bot = FakeBot([{"user_id": 1111, "nickname": "安全名", "card": "[CQ:at,qq=1][[@member_0]]"}])
    name = asyncio.run(_member_display_name(bot, GROUP_ID, 1111))
    assert name == "member_0"
    assert "[" not in name
    assert "@" not in name


def test_member_find_no_match(monkeypatch) -> None:
    clear_social_mention_state()
    install_bot(monkeypatch, [{"user_id": 1111, "nickname": "小明", "card": ""}])
    result = asyncio.run(handle_member_find({"query": "不存在的人"}, make_context()))
    assert result["ok"] is True
    assert result["result"]["matches"] == []
    assert is_social_request(BOT_ID, GROUP_ID, REQUEST_ID)


def test_replace_mention_tokens_grants_only_authorized(monkeypatch) -> None:
    clear_social_mention_state()
    grant_mention(BOT_ID, GROUP_ID, REQUEST_ID, "master", MASTER_QQ)
    text = "主人来啦 [@master_0] 干得好 [[@hacker]] [[@master_0]]"
    out = replace_mention_tokens(text, bot_id=BOT_ID, group_id=GROUP_ID, request_id=REQUEST_ID)
    assert out.count(f"[CQ:at,qq={MASTER_QQ}]") == 2
    assert "[[@hacker]]" not in out
    assert "[@master_0]" not in out


def test_replace_mention_tokens_rejects_name_key(monkeypatch) -> None:
    clear_social_mention_state()
    out = replace_mention_tokens("[[@星乃海獭獭]] 有人找你", bot_id=BOT_ID, group_id=GROUP_ID, request_id=REQUEST_ID)
    assert out == " 有人找你"


def test_replace_mention_tokens_unknown_group_deletes(monkeypatch) -> None:
    clear_social_mention_state()
    grant_mention(BOT_ID, GROUP_ID, REQUEST_ID, "master", MASTER_QQ)
    out = replace_mention_tokens(
        "[[@master_0]]",
        bot_id=BOT_ID,
        group_id=GROUP_ID + 1,
        request_id=REQUEST_ID,
    )
    assert out == ""


def test_replace_mention_tokens_rejects_other_request(monkeypatch) -> None:
    clear_social_mention_state()
    grant_mention(BOT_ID, GROUP_ID, REQUEST_ID, "member", 3447284533)
    out = replace_mention_tokens(
        "[[@member_0]]",
        bot_id=BOT_ID,
        group_id=GROUP_ID,
        request_id="request-2",
    )
    assert out == ""


def test_mention_tokens_are_unique_within_request(monkeypatch) -> None:
    clear_social_mention_state()
    first = grant_mention(BOT_ID, GROUP_ID, REQUEST_ID, "member", 1111)
    second = grant_mention(BOT_ID, GROUP_ID, REQUEST_ID, "member", 2222)
    assert (first, second) == ("member_0", "member_1")
    assert resolve_mention_qq(BOT_ID, GROUP_ID, REQUEST_ID, first) == 1111
    assert resolve_mention_qq(BOT_ID, GROUP_ID, REQUEST_ID, second) == 2222


def test_context_reads_request_id() -> None:
    context = ToolInvokeContext.from_payload({
        "bot_id": BOT_ID,
        "group_id": GROUP_ID,
        "user_id": 9999,
        "request_id": REQUEST_ID,
    })
    assert context is not None
    assert context.request_id == REQUEST_ID


def test_social_domain_inference() -> None:
    assert "social" in infer_tool_domains("把你的主人@出来")
    assert "social" in infer_tool_domains("你的主人是谁")
    assert "social" in infer_tool_domains("群里有没有叫泰坦的人")
    assert "social" in infer_tool_domains("牛牛叫星乃海獭獭出来一下")
    assert "social" in infer_tool_domains("把泰坦叫出来")
    assert "social" not in infer_tool_domains("今天天气怎么样")


def test_social_tools_injected_when_domain_hits(monkeypatch) -> None:
    from pallas.product.llm.tools.registry import ensure_tools_loaded, tool_catalog_for_chat

    ensure_tools_loaded()
    for text in ("把你的主人@出来", "你把你的主人艾特出来"):
        catalog = tool_catalog_for_chat(task="llm_chat", user_text=text)
        assert catalog is not None
        names = {entry.name for entry in catalog.tools}
        assert "social.master.info" in names
