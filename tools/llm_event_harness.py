"""在进程内复现 OneBot V11 到 LLM 投递的测试工具。"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import nonebot
from nonebot.adapters.onebot.v11 import Adapter, Bot

from pallas.product.llm.event_observation import (
    current_event_observation as _event_observation_ctx,
)


@dataclass(frozen=True)
class EventFixture:
    name: str
    event: dict[str, Any]


@dataclass
class EventObservation:
    variant: str
    case: str
    request_id: str | None = None
    route: str | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    prompt_hits: list[str] = field(default_factory=list)
    api_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EventResult:
    variant: str
    case: str
    status: str
    route: str | None = None
    request_id: str | None = None
    reply: str = ""
    api_calls: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    prompt_hits: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "case": self.case,
            "status": self.status,
            "route": self.route,
            "request_id": self.request_id,
            "reply": self.reply,
            "api_calls": self.api_calls,
            "stages": self.stages,
            "error": self.error,
            "prompt_hits": self.prompt_hits,
        }


_harness_owner: ContextVar[str | None] = ContextVar("llm_event_harness_owner", default=None)


class _QuietDirectoryHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


class LocalImageServer:
    """Serve explicitly registered local files from an isolated temporary root."""

    def __init__(self, paths: Sequence[str | Path]) -> None:
        self._paths = [Path(path).expanduser().resolve() for path in paths]
        self._mapping: dict[Path, str] = {}
        self._root: Path | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> LocalImageServer:
        if self._server is not None:
            return self
        root = Path(tempfile.mkdtemp(prefix="pallas-llm-images-"))
        try:
            for index, source in enumerate(self._paths):
                if not source.is_file():
                    raise ValueError(f"local image does not exist: {source}")
                target_name = f"{index}-{source.name}"
                target = root / target_name
                shutil.copyfile(source, target)
                self._mapping[source] = target_name
            handler = partial(_QuietDirectoryHandler, directory=str(root))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        self._root = root
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="llm-image-server", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        host, port = self._running_address()
        return f"http://{host}:{port}"

    def url_for(self, path: str | Path) -> str:
        source = Path(path).expanduser().resolve()
        try:
            filename = self._mapping[source]
        except KeyError as exc:
            raise ValueError(f"local image was not registered: {source}") from exc
        return f"{self.base_url}/{filename}"

    def close(self) -> None:
        server = self._server
        thread = self._thread
        root = self._root
        self._server = None
        self._thread = None
        self._root = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def _running_address(self) -> tuple[str, int]:
        server = self._server
        if server is None:
            raise RuntimeError("local image server is not running")
        host, port = server.server_address[:2]
        return str(host), int(port)


def _cq_escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace(",", "&#44;").replace("[", "&#91;").replace("]", "&#93;")


def _segment_to_cq(segment: Mapping[str, Any]) -> str:
    segment_type = str(segment.get("type") or "")
    data = segment.get("data")
    if not isinstance(data, Mapping):
        data = {}
    if segment_type == "text":
        return str(data.get("text") or "")
    fields = ",".join(
        f"{key}={_cq_escape(value)}" for key, value in data.items() if value is not None and str(value) != ""
    )
    return f"[CQ:{segment_type}{',' + fields if fields else ''}]"


def _segments_to_cq(segments: Sequence[Mapping[str, Any]]) -> str:
    return "".join(_segment_to_cq(segment) for segment in segments)


def build_group_message_payload(
    *,
    text: str,
    images: Sequence[str],
    to_me: bool,
    bot_id: str,
    group_id: int,
    user_id: int,
    message_id: int,
    sender_nickname: str,
    sender_role: str,
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    if to_me:
        segments.append({"type": "at", "data": {"qq": str(bot_id)}})
    if text:
        segments.append({"type": "text", "data": {"text": text}})
    segments += [{"type": "image", "data": {"file": str(image), "url": str(image)}} for image in images]
    raw_message = _segments_to_cq(segments)
    return {
        "time": int(time.time()),
        "self_id": str(bot_id),
        "post_type": "message",
        "sub_type": "normal",
        "user_id": int(user_id),
        "message_type": "group",
        "message_id": int(message_id),
        "message": segments,
        "original_message": raw_message,
        "raw_message": raw_message,
        "font": 0,
        "sender": {
            "user_id": int(user_id),
            "nickname": str(sender_nickname),
            "role": str(sender_role),
        },
        "group_id": int(group_id),
    }


def load_event_fixtures(path: Path) -> list[EventFixture]:
    fixtures: list[EventFixture] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read event fixture: {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in event fixture line {line_number}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"event fixture line {line_number} must be a JSON object")
        event = raw.get("event", raw)
        if not isinstance(event, dict):
            raise ValueError(f"event fixture line {line_number} has a non-object event")
        name = str(raw.get("name") or f"case-{line_number}")
        fixtures.append(EventFixture(name=name, event=event))
    return fixtures


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _message_to_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    extract_plain_text = getattr(message, "extract_plain_text", None)
    if callable(extract_plain_text):
        return str(extract_plain_text())
    if isinstance(message, Sequence) and not isinstance(message, (str, bytes, bytearray)):
        text: list[str] = []
        for segment in message:
            if isinstance(segment, Mapping):
                data = segment.get("data")
                if isinstance(data, Mapping) and segment.get("type") == "text":
                    text.append(str(data.get("text") or ""))
            else:
                text.append(_message_to_text(segment))
        return "".join(text)
    return str(message or "")


class FakeBot(Bot):
    """Only records group text delivery; every other API is rejected."""

    def __init__(self, adapter: Adapter, self_id: str, *, on_call=None) -> None:
        super().__init__(adapter, str(self_id))
        self.calls: list[dict[str, Any]] = []
        self._last_message: Any = None
        self._next_message_id = 1
        self._on_call = on_call

    @property
    def last_message(self) -> Any:
        return self._last_message

    def reply_text(self) -> str:
        return _message_to_text(self._last_message)

    async def call_api(self, api: str, **data: Any) -> Any:
        if api != "send_group_msg":
            raise RuntimeError(f"FakeBot rejected API: {api}")
        self._last_message = data.get("message")
        call = {"action": api, "params": _json_safe(data)}
        self.calls.append(call)
        if self._on_call is not None:
            self._on_call(call)
        message_id = self._next_message_id
        self._next_message_id += 1
        return {"message_id": message_id}


def current_event_observation() -> EventObservation | None:
    return _event_observation_ctx.get()


def _event_bot_id(payload: Mapping[str, Any], event: Any) -> str:
    return str(payload.get("self_id") or getattr(event, "self_id", "pallas-harness"))


def _result_from_observation(
    observation: EventObservation,
    bot: FakeBot | None,
    *,
    status: str,
    error: str | None = None,
) -> EventResult:
    return EventResult(
        variant=observation.variant,
        case=observation.case,
        status=status,
        route=observation.route,
        request_id=observation.request_id,
        reply=bot.reply_text() if bot is not None else "",
        api_calls=list(bot.calls) if bot is not None else [],
        stages=list(observation.stages),
        error=error,
        prompt_hits=list(observation.prompt_hits),
    )


def _stage_recorded(observation: EventObservation, stage: str) -> bool:
    return any(entry.get("stage") == stage for entry in observation.stages)


async def _wait_for_owned_tasks(tasks: set[asyncio.Task[Any]], *, timeout: float) -> bool:  # noqa: ASYNC109
    if not tasks:
        return True
    done, _pending = await asyncio.wait(tasks, timeout=max(0.0, float(timeout)))
    return bool(done)


async def run_event_case(
    fixture: EventFixture,
    *,
    prompt: str,
    provider: str,
    model: str,
    temperature: float,
    timeout: float = 60.0,  # noqa: ASYNC109
    variant: str = "A",
    runtime: Any | None = None,
) -> EventResult:
    """Convert and dispatch one fixture, keeping all harness-owned state local."""

    observation = EventObservation(variant=variant, case=fixture.name)
    observation_token = _event_observation_ctx.set(observation)
    owner_token = _harness_owner.set(f"{variant}:{fixture.name}:{id(observation)}")
    prompt_token = None
    owned_tasks: set[asyncio.Task[Any]] = set()
    dispatch_task: asyncio.Task[Any] | None = None
    bot: FakeBot | None = None
    registered_bot_id = ""
    previous_bot: Any = None
    had_previous_bot = False
    original_create_task = asyncio.create_task
    tracked_llm_tasks: list[asyncio.Task[Any]] = []
    deadline = float(timeout)

    def on_call(call: dict[str, Any]) -> None:
        observation.api_calls.append(call)

    def tracking_create_task(coro, *, name=None, **kwargs):
        task = original_create_task(coro, name=name, **kwargs)
        tracked_llm_tasks.append(task)
        return task

    try:
        from pallas.product.llm.persona_context import llm_chat_prompt_override

        prompt_token = llm_chat_prompt_override.set(prompt)
        if runtime is None:
            runtime = await initialize_event_runtime()
        adapter: Adapter = runtime.adapter
        event = adapter.json_to_event(fixture.event)
        if event is None:
            observation.stages.append({"stage": "adapter", "status": "failed", "reason": "invalid_event"})
            return _result_from_observation(observation, None, status="failed", error="adapter returned no event")

        registered_bot_id = _event_bot_id(fixture.event, event)
        bot = FakeBot(adapter, registered_bot_id, on_call=on_call)
        bots = nonebot.get_bots()
        had_previous_bot = registered_bot_id in bots
        previous_bot = bots.get(registered_bot_id)
        bots[registered_bot_id] = bot
        observation.stages.append({
            "stage": "config",
            "status": "applied",
            "provider": provider,
            "model": model,
            "temperature": temperature,
        })
        observation.stages.append({"stage": "adapter", "status": "converted"})

        dispatch = runtime.dispatch
        # Intercept tasks created by the production handler so we can await its async turn.
        asyncio.create_task = tracking_create_task  # type: ignore[assignment]
        try:
            dispatch_task = original_create_task(dispatch(bot, event), name=f"llm_event_dispatch:{fixture.name}")
            owned_tasks.add(dispatch_task)
            observation.stages.append({"stage": "dispatch", "status": "started"})
            started = time.monotonic()
            await _wait_for_owned_tasks({dispatch_task}, timeout=deadline)
            if not dispatch_task.done():
                raise TimeoutError(f"event dispatch did not finish within {timeout:.2f}s")
            exc = dispatch_task.exception()
            if exc is not None:
                raise exc
            remaining = max(0.0, deadline - (time.monotonic() - started))
            if tracked_llm_tasks:
                await _wait_for_owned_tasks(set(tracked_llm_tasks), timeout=remaining)
        finally:
            asyncio.create_task = original_create_task  # type: ignore[assignment]

        # Resolve a terminal status from observation + Fake Bot.
        if bot.calls:
            observation.stages.append({"stage": "delivery", "status": "delivered"})
            return _result_from_observation(observation, bot, status="delivered")
        if _stage_recorded(observation, "reply_gate"):
            return _result_from_observation(observation, bot, status="gate_skipped")
        if not tracked_llm_tasks:
            observation.stages.append({"stage": "direct_runtime", "status": "handled"})
            return _result_from_observation(observation, bot, status="direct_handled")
        if any(not task.done() for task in tracked_llm_tasks):
            raise TimeoutError(f"event case timed out after {timeout:.2f}s")
        observation.stages.append({"stage": "llm_chat", "status": "no_reply", "reason": "no_bot_send"})
        return _result_from_observation(observation, bot, status="timeout")
    except TimeoutError as exc:
        observation.stages.append({"stage": "wait", "status": "timeout"})
        return _result_from_observation(observation, bot, status="timeout", error=str(exc))
    except Exception as exc:
        observation.stages.append({"stage": "error", "status": "failed", "error": str(exc)[:240]})
        return _result_from_observation(
            observation,
            bot,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        for task in owned_tasks | set(tracked_llm_tasks):
            if not task.done():
                task.cancel()
        pending = [task for task in owned_tasks | set(tracked_llm_tasks) if not task.cancelled()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if registered_bot_id:
            bots = nonebot.get_bots()
            if had_previous_bot:
                bots[registered_bot_id] = previous_bot
            else:
                bots.pop(registered_bot_id, None)
        if prompt_token is not None:
            from pallas.product.llm.persona_context import llm_chat_prompt_override

            llm_chat_prompt_override.reset(prompt_token)
        _harness_owner.reset(owner_token)
        _event_observation_ctx.reset(observation_token)


async def initialize_event_runtime() -> Any:
    """Perform the minimum one-time event-path setup for the CLI tool.

    Loads plugins and registers the production dispatch without starting the
    ASGI/OneBot network, send queues, scheduler, or work-process launcher.
    Idempotent for multiple JSONL cases within one process.
    """

    from pallas.core.platform.message_runtime.lifecycle import configure_direct_runtime

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
        from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

        nonebot.get_driver().register_adapter(OneBotV11Adapter)
    registered = getattr(nonebot.get_driver(), "_adapters", {})
    values = list(registered.values())
    if not values:
        nonebot.get_driver().register_adapter(Adapter)
        values = list(getattr(nonebot.get_driver(), "_adapters", {}).values())
    adapter = values[0]

    configure_direct_runtime()

    from pallas.core.platform.ingress.matcher_dispatch import (
        install_matcher_dispatch,
        matcher_dispatch_enabled,
        patched_handle_event_now,
    )

    if matcher_dispatch_enabled():
        install_matcher_dispatch()

    from pallas.core.platform.ingress.route_index import build_route_index, route_index_enabled

    if route_index_enabled():
        build_route_index()

    return SimpleNamespace(adapter=adapter, dispatch=patched_handle_event_now)
