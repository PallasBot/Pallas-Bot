"""在进程内复现 OneBot V11 到 LLM 投递的测试工具。"""

from __future__ import annotations

import argparse
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
    journey: str = "llm"
    expect: dict[str, Any] | None = None


REDACTION_MASK = "[REDACTED]"

# stage names whose string values are considered body content and redacted by default
_REDACTED_STAGE_KEYS = frozenset({"system", "system_prefix", "prompt", "message", "reply"})


def _redact_stage(stage: dict[str, Any]) -> dict[str, Any]:
    return {key: (REDACTION_MASK if key in _REDACTED_STAGE_KEYS else value) for key, value in stage.items()}


def _redact_api_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted: list[dict[str, Any]] = []
    for call in calls:
        params = dict(call.get("params") or {})
        if "message" in params:
            params["message"] = REDACTION_MASK
        redacted.append({**call, "params": params})
    return redacted


@dataclass
class EventObservation:
    variant: str
    case: str
    journey: str = "llm"
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
    journey: str = "llm"
    route: str | None = None
    request_id: str | None = None
    reply: str = ""
    outbound_actions: list[dict[str, Any]] = field(default_factory=list)
    api_calls: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    assertions: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_class: str | None = None
    prompt_hits: list[str] = field(default_factory=list)
    redaction_summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, redact: bool = False) -> dict[str, Any]:
        if not redact:
            return {
                "variant": self.variant,
                "case": self.case,
                "status": self.status,
                "journey": self.journey,
                "route": self.route,
                "request_id": self.request_id,
                "reply": self.reply,
                "outbound_actions": self.outbound_actions,
                "api_calls": self.api_calls,
                "stages": self.stages,
                "assertions": self.assertions,
                "error": self.error,
                "error_class": self.error_class,
                "prompt_hits": self.prompt_hits,
                "redaction_summary": self.redaction_summary,
            }
        reply = self.reply
        if reply:
            self.redaction_summary["reply_redacted"] = True
            reply = REDACTION_MASK
        return {
            "variant": self.variant,
            "case": self.case,
            "status": self.status,
            "journey": self.journey,
            "route": self.route,
            "request_id": self.request_id,
            "reply": reply,
            "outbound_actions": _redact_api_calls(self.outbound_actions),
            "api_calls": _redact_api_calls(self.api_calls),
            "stages": list(map(_redact_stage, self.stages)),
            "assertions": self.assertions,
            "error": self.error,
            "error_class": self.error_class,
            "prompt_hits": self.prompt_hits,
            "redaction_summary": {
                "mask": REDACTION_MASK,
                **self.redaction_summary,
                "redacted_stage_keys": sorted(_REDACTED_STAGE_KEYS),
            },
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
        journey = str(raw.get("journey") or "llm")
        if journey not in {"command", "matcher", "llm"}:
            raise ValueError(f"event fixture line {line_number} has unknown journey [{journey}]")
        expect = raw.get("expect")
        if expect is not None and not isinstance(expect, dict):
            raise ValueError(f"event fixture line {line_number} has a non-object expect")
        fixtures.append(EventFixture(name=name, event=event, journey=journey, expect=expect))
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


def _result_error_class(error: str | None) -> str | None:
    if not error:
        return None
    return error.split(":", 1)[0].strip() or "Error"


def _result_from_observation(
    observation: EventObservation,
    bot: FakeBot | None,
    *,
    status: str,
    error: str | None = None,
    error_class: str | None = None,
) -> EventResult:
    outbound_actions = list(bot.calls) if bot is not None else []
    if not outbound_actions and bot is not None and bot.last_message is not None:
        outbound_actions = [{"action": "send_group_msg", "params": {"message": REDACTION_MASK}}]
    return EventResult(
        variant=observation.variant,
        case=observation.case,
        status=status,
        journey=observation.journey,
        route=observation.route,
        request_id=observation.request_id,
        reply=bot.reply_text() if bot is not None else "",
        outbound_actions=outbound_actions,
        api_calls=list(bot.calls) if bot is not None else [],
        stages=list(observation.stages),
        error=error,
        error_class=error_class or _result_error_class(error),
        prompt_hits=list(observation.prompt_hits),
        redaction_summary={
            "mask": REDACTION_MASK,
            "redacted_stage_keys": sorted(_REDACTED_STAGE_KEYS),
            "raw_reply_kept": False,
        },
    )


def _repair_hint(result: EventResult) -> str | None:
    if result.status in ("delivered", "direct_handled"):
        if result.assertions and result.assertions.get("passed"):
            return "All expected assertions passed for this journey."
        return "Journey completed; review the captured stages to confirm side-effect parity."
    if result.status == "gate_skipped":
        return "Expected rejection or degrade gate fired without an outbound side effect."
    if result.status in ("timeout", "failed"):
        target = f" for [case={result.case}]"
        detail = result.error_class or result.error or "unknown"
        return f"Investigate the failing journey{target}: status=[{result.status}] error=[{detail}]."
    return "Journey completed; no further action required."


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

    observation = EventObservation(variant=variant, case=fixture.name, journey=fixture.journey)
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
            return _result_from_observation(
                observation,
                None,
                status="failed",
                error="adapter returned no event",
                error_class="InvalidEvent",
            )

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
        if observation.route is None:
            observation.route = {
                "command": "direct",
                "matcher": "matcher",
                "llm": "llm_chat",
            }.get(observation.journey)
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
        return _result_from_observation(
            observation,
            bot,
            status="timeout",
            error=str(exc),
            error_class="TimeoutError",
        )
    except Exception as exc:
        observation.stages.append({"stage": "error", "status": "failed", "error": str(exc)[:240]})
        return _result_from_observation(
            observation,
            bot,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            error_class=type(exc).__name__,
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


def journey_dispatch(journey: str, runtime: Any) -> Any:
    """Select the dispatch callable for a journey.

    The unified ingress dispatch routes through the direct runtime first and
    falls back to the matcher (including the LLM chat matcher) when appropriate.
    The journey label only changes how results are interpreted/asserted and is
    an explicit extension point for a future matcher-only dispatch.
    """
    return getattr(runtime, "dispatch", None) if journey in {"command", "matcher", "llm"} else None


def evaluate_expect(fixture: EventFixture, result: EventResult) -> dict[str, Any]:
    """Compare observed result against the fixture's declarative `expect`.

    Supported expectation keys: ``route``, ``status`` and ``outbound`` (minimum
    number of outbound actions). The returned map drives the ``assertions``
    field of the stable result JSON and the repair hint.
    """
    expect = fixture.expect or {}
    checks: dict[str, bool] = {}
    if "route" in expect:
        checks["route"] = (result.route or "") == str(expect["route"])
    if "status" in expect:
        checks["status"] = (result.status or "") == str(expect["status"])
    if "outbound" in expect:
        checks["outbound"] = len(result.outbound_actions) >= int(expect["outbound"])
    passed = bool(checks) and all(checks.values())
    return {"expected": expect, "checks": checks, "passed": passed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run redacted event fixtures through the message runtime and emit stable JSON results.",
    )
    parser.add_argument("--fixtures", type=Path, required=True, help="Path to a JSONL fixtures file.")
    parser.add_argument(
        "--journey",
        choices=["command", "matcher", "llm"],
        default=None,
        help="Only run fixtures of this journey; default runs all journeys.",
    )
    parser.add_argument("--out", type=Path, help="Optional JSONL file to write results into.")
    parser.add_argument("--prompt", default="", help="LLM system prompt override (only used by the llm journey).")
    parser.add_argument("--provider", default="test-provider")
    parser.add_argument("--model", default="test-model")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


async def run_journey_batch(
    fixtures: list[EventFixture],
    *,
    prompt: str,
    provider: str,
    model: str,
    temperature: float,
    timeout: float,  # noqa: ASYNC109
) -> list[dict[str, Any]]:
    runtime = await initialize_event_runtime()
    results: list[dict[str, Any]] = []
    for fixture in fixtures:
        result = await run_event_case(
            fixture,
            prompt=prompt,
            provider=provider,
            model=model,
            temperature=temperature,
            timeout=timeout,
            runtime=runtime,
        )
        if fixture.expect:
            result.assertions = evaluate_expect(fixture, result)
        row = result.as_dict(redact=True)
        row["repair_hint"] = _repair_hint(result)
        results.append(row)
    return results


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.core.foundation.db import init_db

    apply_repo_settings_to_environ()
    await init_db()

    fixtures = load_event_fixtures(args.fixtures)
    if args.journey:
        fixtures = [fixture for fixture in fixtures if fixture.journey == args.journey]

    results = await run_journey_batch(
        fixtures,
        prompt=args.prompt,
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        timeout=args.timeout,
    )

    for row in results:
        print(json.dumps(row, ensure_ascii=False, indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as handle:
            for row in results:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {len(results)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
