from unittest.mock import MagicMock, patch

import httpx
import pytest

from pallas.product.community_stats.endpoints import PRIMARY_CORPUS_API_BASE
from pallas.product.corpus.community_source import RemoteCorpusRepository


@pytest.fixture(autouse=True)
def open_remote_corpus_budget(monkeypatch):
    from pallas.product.corpus import community_source as mod
    from pallas.product.corpus.remote_budget import clear_remote_corpus_budget_state

    class _OpenBudget:
        skipped = False

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    clear_remote_corpus_budget_state()
    budgets: list[_OpenBudget] = []

    def _factory(**kwargs):
        budget = _OpenBudget(**kwargs)
        budgets.append(budget)
        return budget

    monkeypatch.setattr(
        "pallas.product.corpus.remote_budget.RemoteCorpusBudget",
        _factory,
    )
    mod._shared_client = None
    mod._shared_client_timeout = None
    yield budgets
    mod._shared_client = None
    mod._shared_client_timeout = None
    clear_remote_corpus_budget_state()


@pytest.mark.asyncio
async def test_find_by_keywords_failover_to_secondary_base():
    secondary = "https://stats.example/v1/corpus"
    calls: list[str] = []

    async def fake_get(self, url, **kwargs):
        calls.append(url)
        if url.startswith(PRIMARY_CORPUS_API_BASE):
            raise httpx.ConnectError("name or service not known", request=MagicMock())
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {
            "keywords": "test",
            "time": 1,
            "trigger_count": 1,
            "answers": [],
            "ban": [],
            "clear_time": 0,
        }
        return mock

    repo = RemoteCorpusRepository(
        api_bases=[PRIMARY_CORPUS_API_BASE, secondary],
        token="pc_test",
    )
    with patch.object(httpx.AsyncClient, "get", fake_get):
        ctx = await repo.find_by_keywords("test")
    assert ctx is not None
    assert ctx.keywords == "test"
    assert calls[0] == f"{PRIMARY_CORPUS_API_BASE}/context"
    assert calls[1] == f"{secondary}/context"


@pytest.mark.asyncio
async def test_find_by_keywords_404_returns_none():
    async def fake_get(self, url, **kwargs):
        mock = MagicMock()
        mock.status_code = 404
        return mock

    repo = RemoteCorpusRepository(api_base=PRIMARY_CORPUS_API_BASE, token="pc_test")
    with patch.object(httpx.AsyncClient, "get", fake_get):
        assert await repo.find_by_keywords("四轮 成品") is None


@pytest.mark.asyncio
async def test_find_by_keywords_all_bases_fail_raises():
    secondary = "https://stats.example/v1/corpus"
    repo = RemoteCorpusRepository(
        api_bases=[PRIMARY_CORPUS_API_BASE, secondary],
        token="pc_test",
    )

    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("down", request=MagicMock())

    with patch.object(httpx.AsyncClient, "get", fake_get):
        with pytest.raises(httpx.ConnectError):
            await repo.find_by_keywords("test")


@pytest.mark.asyncio
async def test_contribute_waits_for_remote_budget_slot(open_remote_corpus_budget):
    async def fake_post(self, url, **kwargs):
        mock = MagicMock()
        mock.status_code = 200
        mock.text = ""
        return mock

    repo = RemoteCorpusRepository(api_base=PRIMARY_CORPUS_API_BASE, token="pc_test")
    with patch.object(httpx.AsyncClient, "post", fake_post):
        await repo.upsert_answer(
            keywords="kw",
            group_id=0,
            answer_keywords="ans",
            answer_time=1,
            message="hi",
            append_on_existing=True,
        )
    assert open_remote_corpus_budget[-1].kwargs.get("wait") is True
    assert open_remote_corpus_budget[-1].kwargs.get("hot_path") is False
