"""社区语料 HTTP 仓储。"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.db.modules import Answer, Ban, Context
from pallas.core.foundation.db.repository import ContextRepositoryExistenceMixin
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise


def remote_corpus_timeout_sec() -> float:
    raw = repo_env_raw_value("PALLAS_CORPUS_REMOTE_TIMEOUT_SEC")
    if raw is not None:
        try:
            return max(0.5, float(str(raw).strip()))
        except ValueError:
            pass
    return 2.0


_shared_client: httpx.AsyncClient | None = None
_shared_client_timeout: float | None = None
_shared_client_lock = asyncio.Lock()


async def shared_remote_corpus_client(timeout_sec: float) -> httpx.AsyncClient:
    global _shared_client, _shared_client_timeout
    timeout = max(0.5, float(timeout_sec))
    async with _shared_client_lock:
        if _shared_client is None or _shared_client_timeout != timeout:
            if _shared_client is not None:
                await _shared_client.aclose()
            _shared_client = httpx.AsyncClient(timeout=timeout)
            _shared_client_timeout = timeout
    return _shared_client


class RemoteCorpusRepository(ContextRepositoryExistenceMixin):
    def __init__(
        self,
        *,
        api_base: str = "",
        api_bases: list[str] | None = None,
        token: str,
        timeout_sec: float | None = None,
    ) -> None:
        bases = list(api_bases or [])
        if not bases and api_base:
            bases = [api_base]
        seen: set[str] = set()
        self._api_bases: list[str] = []
        for base in bases:
            norm = (base or "").strip().rstrip("/")
            if norm and norm not in seen:
                seen.add(norm)
                self._api_bases.append(norm)
        self._token = (token or "").strip()
        self._timeout = remote_corpus_timeout_sec() if timeout_sec is None else max(0.5, float(timeout_sec))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    async def schedule_auth_refresh() -> None:
        from pallas.product.corpus.enroll import maybe_refresh_corpus_enrollment_on_auth_failure

        await maybe_refresh_corpus_enrollment_on_auth_failure()

    async def find_by_keywords(self, keywords: str) -> Context | None:
        if not keywords or not self._api_bases:
            return None
        from pallas.product.corpus.remote_budget import RemoteCorpusBudget

        async with RemoteCorpusBudget(hot_path=True, wait=False) as budget:
            if budget.skipped:
                return None
            return await self._find_by_keywords_http(keywords)

    async def _find_by_keywords_http(self, keywords: str) -> Context | None:
        last_error: httpx.HTTPError | None = None
        try:
            async with scrub_http_log_noise():
                client = await shared_remote_corpus_client(self._timeout)
                for base in self._api_bases:
                    context_url = f"{base}/context"
                    if not context_url.startswith("http"):
                        continue
                    try:
                        resp = await client.get(
                            context_url,
                            params={"keywords": keywords},
                            headers=self._headers(),
                        )
                    except httpx.HTTPError as e:
                        last_error = e
                        logger.warning(f"corpus community find failed api_base={base}: {e}")
                        continue
                    if resp.status_code == 401:
                        asyncio.create_task(self.schedule_auth_refresh())
                        return None
                    if resp.status_code == 404:
                        return None
                    if resp.status_code != 200:
                        preview = (resp.text or "")[:200]
                        logger.warning(f"corpus community find HTTP {resp.status_code} api_base={base}: {preview}")
                        continue
                    data = resp.json()
                    if not isinstance(data, dict):
                        return None
                    return self._context_from_payload(data)
        except httpx.HTTPError as e:
            logger.warning(f"corpus community find failed: {e}")
            raise
        if last_error is not None:
            raise last_error
        return None

    async def save(self, context: Context) -> None:
        return None

    async def insert(self, context: Context) -> None:
        await self._post_contribute({"op": "insert", "context": self._context_to_payload(context)})

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        return None

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        return []

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        await self._post_contribute({
            "op": "upsert_answer",
            "keywords": keywords,
            "group_id": int(group_id),
            "answer_keywords": answer_keywords,
            "answer_time": int(answer_time),
            "message": message,
            "append_on_existing": bool(append_on_existing),
        })

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        return None

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        return None

    async def find_ban_reply_target(self, group_id: int, reply_message: str) -> tuple[str, str] | None:
        return None

    async def _post_contribute(self, body: dict[str, Any]) -> None:
        if not self._api_bases:
            return
        from pallas.product.corpus.remote_budget import RemoteCorpusBudget

        async with RemoteCorpusBudget(hot_path=False, wait=False) as budget:
            if budget.skipped:
                return
            await self._post_contribute_http(body)

    async def _post_contribute_http(self, body: dict[str, Any]) -> None:
        last_error: httpx.HTTPError | None = None
        try:
            async with scrub_http_log_noise():
                client = await shared_remote_corpus_client(self._timeout)
                for base in self._api_bases:
                    contribute_url = f"{base}/contribute"
                    if not contribute_url.startswith("http"):
                        continue
                    try:
                        resp = await client.post(contribute_url, json=body, headers=self._headers())
                    except httpx.HTTPError as e:
                        last_error = e
                        logger.warning(f"corpus community contribute failed api_base={base}: {e}")
                        continue
                    if resp.status_code in (200, 202):
                        return
                    body_preview = (resp.text or "")[:200]
                    logger.warning(
                        f"corpus community contribute HTTP {resp.status_code} api_base={base}: {body_preview}"
                    )
        except httpx.HTTPError as e:
            logger.warning(f"corpus community contribute failed: {e}")
            raise
        if last_error is not None:
            raise last_error

    @staticmethod
    def _context_from_payload(data: dict[str, Any]) -> Context:
        answers_raw = data.get("answers")
        answers: list[Answer] = []
        if isinstance(answers_raw, list):
            for item in answers_raw:
                if not isinstance(item, dict):
                    continue
                answers.append(
                    Answer(
                        keywords=str(item.get("keywords") or ""),
                        group_id=int(item.get("group_id") or 0),
                        count=int(item.get("count") or 1),
                        time=int(item.get("time") or 0),
                        messages=[str(m) for m in (item.get("messages") or []) if m is not None],
                    )
                )
        ban_raw = data.get("ban")
        bans: list[Ban] = []
        if isinstance(ban_raw, list):
            for item in ban_raw:
                if not isinstance(item, dict):
                    continue
                bans.append(
                    Ban(
                        keywords=str(item.get("keywords") or ""),
                        group_id=int(item.get("group_id") or 0),
                        reason=str(item.get("reason") or ""),
                        time=int(item.get("time") or 0),
                    )
                )
        return Context.model_construct(
            keywords=str(data.get("keywords") or ""),
            time=int(data.get("time") or 0),
            trigger_count=int(data.get("trigger_count") or data.get("count") or 1),
            answers=answers,
            ban=bans,
            clear_time=int(data.get("clear_time") or 0),
        )

    @staticmethod
    def _context_to_payload(context: Context) -> dict[str, Any]:
        return {
            "keywords": context.keywords,
            "time": int(context.time),
            "trigger_count": int(context.trigger_count),
            "clear_time": int(context.clear_time),
            "answers": [
                {
                    "keywords": a.keywords,
                    "group_id": int(a.group_id),
                    "count": int(a.count),
                    "time": int(a.time),
                    "messages": list(a.messages),
                }
                for a in context.answers
            ],
            "ban": [
                {
                    "keywords": b.keywords,
                    "group_id": int(b.group_id),
                    "reason": b.reason,
                    "time": int(b.time),
                }
                for b in context.ban
            ],
        }
