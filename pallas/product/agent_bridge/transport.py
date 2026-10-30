"""Sole original text bridge transport for a maim-message Legacy MessageServer.

Wire layer only: the Pallas ingress path runs review/cmd_perm gates before
``forward_event`` and the product callback re-checks review, group switch and
send queue before delivery. One platform connection carries the startup account
set and one shared allow-list; plain text only, no reconnect, no send queue, an
in-process dedup window only, and no ACK or automatic replay. Reaching this
module does not mean a real MaiBot/QQ integration was verified.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import aiohttp

from pallas.product.agent_bridge.native_compat import AUTHORITY_FIELD

MAX_TEXT_LEN = 2000
MAX_FRAME_BYTES = 256 * 1024
DEDUP_WINDOW = 512
ERROR_WINDOW = 64
ID_MAX_LEN = 18
MESSAGE_ID_MAX_LEN = 256
INBOUND_ID_MAX_LEN = 255
CQ_MARKER = "[CQ:"


class BridgeDisabledError(RuntimeError):
    """Raised when the scope is disabled but a connection or send is requested."""


class BridgeNotConnectedError(RuntimeError):
    """Raised when sending while disconnected; the bridge never buffers."""


@dataclass(frozen=True)
class BridgeScope:
    """Fixed account-set connection scope. Disabled by default.

    One scope covers one platform's shared WebSocket and one startup account
    snapshot. Single-account construction (``bot_id``) stays compatible; a
    multi-account scope is built with ``bot_ids`` and never guesses a first bot.
    """

    enabled: bool = False
    bot_id: int = 0
    allowed_group_ids: frozenset[int] = frozenset()
    platform: str = ""
    bot_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_group_ids", frozenset(self.allowed_group_ids))
        effective = frozenset(self.bot_ids)
        if self.bot_id:
            effective = effective | {self.bot_id}
        object.__setattr__(self, "bot_ids", effective)
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if not self.enabled:
            return
        if not self.bot_ids or not all(_is_positive_int(bot) for bot in self.bot_ids):
            raise ValueError("bot_ids must be a non-empty set of positive integers")
        if not self.allowed_group_ids or not all(_is_positive_int(group) for group in self.allowed_group_ids):
            raise ValueError("allowed_group_ids must be a non-empty set of positive integers")
        if not isinstance(self.platform, str) or not self.platform:
            raise ValueError("platform must be a non-empty string")

    @property
    def multi_account(self) -> bool:
        return len(self.bot_ids) > 1

    def owns_bot(self, bot_id: object) -> bool:
        try:
            return int(bot_id) in self.bot_ids  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False


class MaiBotBridge:
    """One aiohttp WebSocket per platform carrying the startup account set; text in, text out."""

    def __init__(self, scope: BridgeScope, send_reply: Callable[[int, int, str], Awaitable[int]]) -> None:
        self.scope = scope
        self.send_reply = send_reply
        # ponytail: in-process dedup window only; no cross-restart exactly-once.
        self._seen_inbound: deque[tuple[int, int, int]] = deque(maxlen=DEDUP_WINDOW)
        self._seen_outbound: deque[tuple[int, int, str]] = deque(maxlen=DEDUP_WINDOW)
        self.errors: deque[str] = deque(maxlen=ERROR_WINDOW)
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, url: str, token: str | None = None) -> None:
        if not self.scope.enabled:
            raise BridgeDisabledError("bridge scope is disabled; refusing to open a connection")
        if self._ws is not None:
            raise BridgeNotConnectedError("bridge already has an active connection")
        headers = {"platform": self.scope.platform}
        if token:
            headers["authorization"] = token
        session = aiohttp.ClientSession()
        try:
            ws = await session.ws_connect(url, headers=headers, heartbeat=20, max_msg_size=MAX_FRAME_BYTES)
        except BaseException:
            await session.close()
            raise
        self._session = session
        self._ws = ws
        self._connected = True
        self._closed.clear()
        self._reader = asyncio.create_task(self._read_loop(ws), name="maibot-bridge.read")

    async def forward_event(
        self,
        event: Mapping[str, object],
        *,
        command_traffic: bool,
        at_bot: bool = False,
        is_mentioned: bool = False,
    ) -> None:
        if not self.scope.enabled:
            raise BridgeDisabledError("bridge scope is disabled; refusing to forward")
        if command_traffic:
            return
        if self._ws is None or self._ws.closed:
            raise BridgeNotConnectedError("bridge is not connected; refusing to buffer")
        parsed = _parse_onebot_group_event(event, self.scope)
        if parsed is None:
            self._record_error("inbound event rejected by identity or shape validation")
            return
        bot_id, group_id, user_id, message_id, text = parsed
        key = (bot_id, group_id, message_id)
        if key in self._seen_inbound:
            return
        internal_id = _inbound_internal_id(bot_id, group_id, message_id, multi=self.scope.multi_account)
        if len(internal_id) > INBOUND_ID_MAX_LEN:
            self._record_error("inbound internal id exceeds the upstream length limit")
            return
        self._seen_inbound.append(key)
        additional: dict[str, object] = {
            "account_id": str(bot_id),
            AUTHORITY_FIELD: {
                "schema_version": 1,
                "account_id": str(bot_id),
                "at_bot": bool(at_bot),
                "is_mentioned": bool(at_bot or is_mentioned),
            },
        }
        if self.scope.multi_account:
            additional["original_message_id"] = str(message_id)
        if at_bot:
            additional["at_bot"] = True
        if is_mentioned:
            additional["is_mentioned"] = True
        await self._send_json({
            "account_id": str(bot_id),
            "message_info": {
                "platform": self.scope.platform,
                "message_id": internal_id,
                "time": event.get("time", time.time()),
                "group_info": {"platform": self.scope.platform, "group_id": str(group_id)},
                "user_info": {"platform": self.scope.platform, "user_id": str(user_id)},
                "additional_config": additional,
            },
            "message_segment": {"type": "text", "data": text},
        })

    async def wait_closed(self) -> None:
        task = self._reader
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception as exc:  # surfaced through errors, not lost
                self._record_error(f"reader task ended with an error: {type(exc).__name__}: {exc}")
        await self._closed.wait()

    async def close(self) -> None:
        task, ws, session = self._reader, self._ws, self._session
        self._reader = self._ws = self._session = None
        self._connected = False
        try:
            if ws is not None and not ws.closed:
                await ws.close()
        except Exception as exc:
            self._record_error(f"closing the socket failed: {type(exc).__name__}: {exc}")
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    self._record_error(f"reader task ended with an error: {type(exc).__name__}: {exc}")
            if session is not None and not session.closed:
                await session.close()
            self._closed.set()

    async def stop(self) -> None:
        await self.close()

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self._handle_text(msg.data)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._record_error(f"reader handler failed: {type(exc).__name__}: {exc}")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_error(f"reader loop failed: {type(exc).__name__}: {exc}")
        finally:
            self._connected = False
            self._closed.set()

    async def _handle_text(self, raw: str) -> None:
        if len(raw) > MAX_FRAME_BYTES:
            self._record_error("inbound frame exceeds the size limit")
            return
        try:
            payload = json.loads(raw)
        except ValueError:
            self._record_error("inbound frame is not valid JSON")
            return
        if not isinstance(payload, Mapping):
            self._record_error("inbound frame is not a JSON object")
            return
        if payload.get("is_custom_message"):
            return
        info = payload.get("message_info")
        if not isinstance(info, Mapping):
            self._record_error("inbound frame is not a standard message")
            return
        await self._handle_reply(payload, info)

    async def _handle_reply(self, payload: Mapping[str, object], info: Mapping[str, object]) -> None:
        if info.get("platform") != self.scope.platform:
            self._record_error("reply platform does not match the bound scope")
            return
        internal_id = info.get("message_id")
        if not isinstance(internal_id, str) or not internal_id.strip() or len(internal_id) > MESSAGE_ID_MAX_LEN:
            self._record_error("reply is missing a usable message_id")
            return
        bot_id, reason = _resolve_outbound_bot(payload, info, self.scope)
        if bot_id is None:
            self._record_error(f"reply account identity rejected: {reason}")
            return
        group = info.get("group_info")
        group_id = _positive_int(group.get("group_id")) if isinstance(group, Mapping) else None
        if group_id is None or group_id not in self.scope.allowed_group_ids:
            self._record_error("reply targets a group outside the allow-list")
            return
        text = _extract_text(payload.get("message_segment"))
        if text is None:
            self._record_error("reply is not bounded plain text")
            return
        key = (bot_id, group_id, internal_id)
        if key in self._seen_outbound:
            return
        # The callback may already have delivered a message, so mark before the
        # side effect; a duplicate frame must never call it a second time.
        self._seen_outbound.append(key)
        try:
            actual_id = await self.send_reply(bot_id, group_id, text)
        except Exception as exc:  # recorded, not silently swallowed
            self._record_error(f"send_reply failed: {type(exc).__name__}: {exc}")
            return
        if not _is_positive_int(actual_id):
            self._record_error("send_reply did not return a positive integer message id")
            return
        if self.scope.multi_account:
            return  # multi-account: a bare-id echo would bulk-update every account
        try:
            await self._send_json({
                "platform": self.scope.platform,
                "message_type_name": "message_id_echo",
                "timestamp": time.time(),
                "is_custom_message": True,
                "content": {"type": "echo", "echo": internal_id, "actual_id": str(actual_id)},
            })
        except BridgeNotConnectedError:
            self._record_error("connection dropped before the echo could be sent")

    async def _send_json(self, payload: Mapping[str, object]) -> None:
        if self._ws is None or self._ws.closed:
            raise BridgeNotConnectedError("bridge is not connected")
        try:
            await self._ws.send_str(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            self._record_error(f"sending failed: {type(exc).__name__}: {exc}")
            raise BridgeNotConnectedError(f"sending failed: {type(exc).__name__}") from exc

    def _record_error(self, message: str) -> None:
        self.errors.append(message)


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and 0 < len(value) <= ID_MAX_LEN and value.isascii() and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _resolve_outbound_bot(
    payload: Mapping[str, object],
    info: Mapping[str, object],
    scope: BridgeScope,
) -> tuple[int | None, str]:
    """Resolve the reply's target account from explicit claims plus the Bot sender.

    Explicit ``account_id`` claims (``additional_config`` / ``info`` / payload)
    must be well-formed, agree with each other, and be in the startup account set.
    ``message_info.user_info.user_id`` is the Bot sender in a normal Legacy reply;
    multi-account scopes strictly validate it. Only single-account scopes retain
    legacy human-sender compatibility and the fixed-binding identity fallback.
    """
    explicit: list[int] = []
    for source in (info.get("additional_config"), info, payload):
        if isinstance(source, Mapping) and source.get("account_id") is not None:
            parsed = _positive_int(source.get("account_id"))
            if parsed is None:
                return None, "malformed_account_id"
            explicit.append(parsed)
    if len(set(explicit)) > 1:
        return None, "conflicting_account_id"
    user_info = info.get("user_info")
    sender_raw = user_info.get("user_id") if isinstance(user_info, Mapping) else None
    sender_present = sender_raw is not None
    sender = _positive_int(sender_raw) if sender_present else None
    if scope.multi_account:
        # The sender slot is the Bot sender in a Legacy reply: when present it must
        # be a managed account and agree with every explicit claim.
        if sender_present:
            if sender is None:
                return None, "malformed_sender"
            if sender not in scope.bot_ids:
                return None, "unknown_sender"
            if explicit and explicit[0] != sender:
                return None, "sender_conflicts_with_claim"
            return sender, ""
        if explicit:
            if explicit[0] not in scope.bot_ids:
                return None, "unknown_account_id"
            return explicit[0], ""
        return None, "missing_account_identity"
    # Single account keeps the legacy human-sender compatibility.
    if explicit:
        if explicit[0] not in scope.bot_ids:
            return None, "unknown_account_id"
        if sender is not None and sender in scope.bot_ids and sender != explicit[0]:
            return None, "sender_conflicts_with_claim"
        return explicit[0], ""
    if sender is not None and sender in scope.bot_ids:
        return sender, ""
    return next(iter(scope.bot_ids)), ""


def _inbound_internal_id(bot_id: int, group_id: int, message_id: int, *, multi: bool) -> str:
    if multi:
        return f"pallas:{bot_id}:{group_id}:{message_id}"
    return str(message_id)


def _extract_text(segment: object) -> str | None:
    if not isinstance(segment, Mapping):
        return None
    kind = segment.get("type")
    if kind == "text":
        data = segment.get("data")
        return _plain_text(data) if isinstance(data, str) else None
    if kind == "seglist":
        items = segment.get("data")
        if not isinstance(items, list) or not items:
            return None
        parts: list[str] = []
        for item in items:
            if not isinstance(item, Mapping) or item.get("type") != "text" or not isinstance(item.get("data"), str):
                return None
            parts.append(item["data"])
        return _plain_text("".join(parts))
    return None


def _event_text(message: object) -> str | None:
    if isinstance(message, str):
        return _plain_text(message)
    if isinstance(message, list) and message:
        parts: list[str] = []
        for item in message:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                return None
            data = item.get("data")
            if not isinstance(data, Mapping) or not isinstance(data.get("text"), str):
                return None
            parts.append(data["text"])
        return _plain_text("".join(parts))
    return None


def _plain_text(text: str) -> str | None:
    # ponytail: plain text only; never smuggle CQ codes or blank content through.
    if not text.strip() or len(text) > MAX_TEXT_LEN or CQ_MARKER in text.upper():
        return None
    return text


def _parse_onebot_group_event(event: Mapping[str, object], scope: BridgeScope) -> tuple[int, int, int, int, str] | None:
    if not isinstance(event, Mapping) or event.get("post_type") != "message" or event.get("message_type") != "group":
        return None
    bot_id = _event_id(event.get("self_id"))
    group_id = _event_id(event.get("group_id"))
    user_id = _event_id(event.get("user_id"))
    message_id = _event_id(event.get("message_id"))
    if bot_id is None or not scope.owns_bot(bot_id):
        return None
    if group_id is None or user_id is None or message_id is None:
        return None
    if group_id not in scope.allowed_group_ids:
        return None
    if user_id in scope.bot_ids:
        return None  # never forward a managed peer account's own message
    text = _event_text(event.get("message"))
    if text is None:
        return None
    return bot_id, group_id, user_id, message_id, text


def _event_id(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
