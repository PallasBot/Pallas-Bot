"""Tests for Repository Protocol interfaces."""

import pytest

from pallas.core.foundation.db.repository import (
    BlackListRepository,
    ContextRepository,
    ContextRepositoryExistenceMixin,
    MessageRepository,
)


class MockContextRepo(ContextRepositoryExistenceMixin):
    async def find_by_keywords(self, keywords):  # noqa: ARG002
        return None

    async def save(self, context):
        pass

    async def insert(self, context):
        pass

    async def delete_expired(self, expiration, threshold):
        pass

    async def find_for_cleanup(self, trigger_threshold, expiration):
        return []

    async def upsert_answer(self, keywords, group_id, answer_keywords, answer_time, message, append_on_existing):
        pass

    async def replace_answers(self, keywords, answers, clear_time):
        pass

    async def append_ban(self, keywords, ban):
        pass

    async def find_ban_reply_target(self, group_id, reply_message):
        return None

    async def list_answers_for_group_since(self, group_id, cutoff_time):
        return []


class MockMessageRepo:
    async def bulk_insert(self, messages):
        pass

    async def find_recent_in_group(self, group_id, **kwargs):
        return []

    async def find_by_message_ids(self, group_id, message_ids):
        return []

    async def list_group_messages_after(self, group_id, **kwargs):
        return []

    async def list_recent_group_ids_for_bot(self, bot_id, **kwargs):
        return []

    async def list_recent_bot_ids_for_group(self, group_id, **kwargs):
        return []


class MockBlackListRepo:
    async def find_all(self):
        return []

    async def upsert_answers(self, group_id, answers):
        pass

    async def upsert_answers_reserve(self, group_id, answers):
        pass

    async def upsert_many_blacklist(self, entries):
        pass


def test_context_repo_protocol():
    repo = MockContextRepo()
    assert isinstance(repo, ContextRepository)


@pytest.mark.asyncio
async def test_existence_mixin_delegates_to_find():
    class _Repo(ContextRepositoryExistenceMixin):
        async def find_by_keywords(self, kw: str):
            return object() if kw == "hit" else None

    repo = _Repo()
    assert await repo.context_exists_by_keywords("hit") is True
    assert await repo.context_exists_by_keywords("miss") is False


def test_message_repo_protocol():
    repo = MockMessageRepo()
    assert isinstance(repo, MessageRepository)


def test_blacklist_repo_protocol():
    repo = MockBlackListRepo()
    assert isinstance(repo, BlackListRepository)


class IncompleteContextRepo:
    async def find_by_keywords(self, keywords):
        return None

    # Missing other methods


def test_incomplete_repo_fails_protocol():
    repo = IncompleteContextRepo()
    assert not isinstance(repo, ContextRepository)
