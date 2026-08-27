"""LLM turn telemetry：只记录形态、关联 hash 和生命周期结果。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import threading
import time
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.logging import log_rate_limited
from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA_VERSION = 1
_DEFAULT_ROOT_NAME = "llm_telemetry"
_KEY_NAME = "hmac.key"
_KEY_SIZE = 32
_HASH_PREFIX = "h:"
_LOCK = threading.Lock()
_DEFAULT_WRITER: TurnTelemetryWriter | None = None

_STAGES = frozenset({
    "ingress",
    "speak",
    "reply_gate",
    "necessity",
    "submit",
    "provider",
    "output",
    "delivery",
})
_DECISIONS = frozenset({
    "proceed",
    "skip",
    "defer",
    "accepted",
    "low_engagement",
    "failed",
    "called",
    "success",
    "silent",
    "partial",
    "sent",
    "skipped",
})
_SHAPE_KEYS = frozenset({
    "text_len",
    "len_bucket",
    "emoji_only",
    "punctuation_only",
    "numeric_only",
    "ascii_only",
    "short_social",
    "short_vent",
    "question",
    "reply_obligation",
    "direct_request",
    "has_cq",
})
_EVENT_KEYS = frozenset({
    "schema_version",
    "ts",
    "turn_id",
    "stage",
    "decision",
    "reason",
    "request_id_hash",
    "message_id_hash",
    "input_message_id_hashes",
    "scope_hashes",
    "hash_status",
    "is_to_me",
    "speak_trigger",
    "shape",
    "text_hash",
    "necessity",
    "provider",
    "model",
    "request_method",
    "call_index",
    "attempt",
    "latency_ms",
    "failure_class",
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost",
    "currency",
    "output_filter_action",
    "output_filter_reason",
    "fallback",
    "segment_count",
    "delivery_status",
    "sent_bubble_count",
    "total_bubble_count",
    "sent_message_id_hashes",
})
_CODE_RE = re.compile(r"[^a-z0-9_-]+")
_EMOJI_ONLY_RE = re.compile(
    r"^[\s\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0000200D❤️🧡💛💚💙💜🖤🤍🤎💢]+$",
    re.UNICODE,
)
_DIRECT_REQUEST_TERMS = ("帮我", "帮忙", "能不能", "可以吗", "要不要")


def _default_instance_id() -> str:
    host = re.sub(r"[^a-zA-Z0-9_-]+", "_", socket.gethostname())[:48] or "host"
    return f"{host}-{os.getpid()}"


def _local_ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _day_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _len_bucket(length: int) -> str:
    if length <= 0:
        return "0"
    if length == 1:
        return "1"
    if length == 2:
        return "2"
    if length <= 4:
        return "3-4"
    if length <= 8:
        return "5-8"
    if length <= 12:
        return "9-12"
    if length <= 24:
        return "13-24"
    if length <= 40:
        return "25-40"
    if length <= 80:
        return "41-80"
    return "81+"


def _is_punctuation_only(text: str) -> bool:
    return bool(text) and all(unicodedata.category(char).startswith("P") for char in text)


def _is_numeric_only(text: str) -> bool:
    return bool(text) and all(char.isnumeric() for char in text)


def new_turn_id() -> str:
    return uuid.uuid4().hex


def hash_value(value: object, *, key: bytes | None) -> str | None:
    if key is None:
        return None
    raw = str(value or "").encode("utf-8", errors="replace")
    digest = hmac.new(key, raw, hashlib.sha256).hexdigest()
    return f"{_HASH_PREFIX}{digest}"


def telemetry_metadata(metadata: object) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    turn_id = str(metadata.get("turn_id") or "").strip()
    return {"turn_id": turn_id} if turn_id else {}


def classify_text_shape(text: str, *, has_cq: bool = False) -> dict[str, object]:
    plain = str(text or "").strip()
    length = len(plain)
    from pallas.product.llm.reply_necessity import (
        has_reply_obligation,
        is_low_value_social_turn,
        is_short_vent,
    )

    return {
        "text_len": length,
        "len_bucket": _len_bucket(length),
        "emoji_only": bool(_EMOJI_ONLY_RE.fullmatch(plain)) if plain else False,
        "punctuation_only": _is_punctuation_only(plain),
        "numeric_only": _is_numeric_only(plain),
        "ascii_only": bool(plain) and all(ord(char) < 128 for char in plain),
        "short_social": is_low_value_social_turn(plain),
        "short_vent": is_short_vent(plain),
        "question": "?" in plain or "？" in plain,
        "reply_obligation": has_reply_obligation(plain),
        "direct_request": any(term in plain for term in _DIRECT_REQUEST_TERMS),
        "has_cq": bool(has_cq),
    }


def _safe_code(value: object, *, fallback: str = "unknown") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return fallback
    code = _CODE_RE.sub("_", raw).strip("_")
    return code[:64] or fallback


def _hash_many(values: object, *, key: bytes | None) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return [hashed for item in values if (hashed := hash_value(item, key=key))]


def build_turn_event(
    *,
    turn_id: str,
    stage: str,
    decision: str,
    reason: str | None = None,
    text: str = "",
    has_cq: bool = False,
    hash_key: bytes | None = None,
    message_id: object = None,
    input_message_ids: object = None,
    request_id: object = None,
    scope: object = None,
    is_to_me: bool | None = None,
    speak_trigger: str | None = None,
    score: int | None = None,
    factors: object = None,
    provider: str | None = None,
    model: str | None = None,
    request_method: str | None = None,
    call_index: int | None = None,
    attempt: int | None = None,
    latency_ms: int | None = None,
    failure_class: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    cost: float | None = None,
    currency: str | None = None,
    output_filter_action: str | None = None,
    output_filter_reason: str | None = None,
    fallback: bool | None = None,
    segment_count: int | None = None,
    delivery_status: str | None = None,
    sent_bubble_count: int | None = None,
    total_bubble_count: int | None = None,
    sent_message_ids: object = None,
    **context: object,
) -> dict[str, object]:
    if stage not in _STAGES:
        raise ValueError(f"unsupported telemetry stage: {stage}")
    if decision not in _DECISIONS:
        raise ValueError(f"unsupported telemetry decision: {decision}")
    event: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "ts": _local_ts(),
        "turn_id": str(turn_id),
        "stage": stage,
        "decision": decision,
        "shape": classify_text_shape(text, has_cq=has_cq),
        "hash_status": "ok" if hash_key is not None else "hash_unavailable",
    }
    if reason:
        event["reason"] = _safe_code(reason)
    if request_id is not None:
        event["request_id_hash"] = hash_value(request_id, key=hash_key)
    if message_id is not None:
        event["message_id_hash"] = hash_value(message_id, key=hash_key)
    input_hashes = _hash_many(input_message_ids, key=hash_key)
    if input_hashes:
        event["input_message_id_hashes"] = input_hashes
    if isinstance(scope, dict):
        scope_hashes = {
            str(name): hashed
            for name, value in scope.items()
            if str(name) in {"bot", "group", "user"} and (hashed := hash_value(value, key=hash_key))
        }
        if scope_hashes:
            event["scope_hashes"] = scope_hashes
    if hash_key is not None:
        event["text_hash"] = hash_value(text, key=hash_key)
    if is_to_me is not None:
        event["is_to_me"] = bool(is_to_me)
    if speak_trigger:
        event["speak_trigger"] = _safe_code(speak_trigger)
    if score is not None or factors is not None:
        event["necessity"] = {
            "score": int(score or 0),
            "factors": [_safe_code(item) for item in factors] if isinstance(factors, (list, tuple)) else [],
        }
    optional_values = {
        "provider": provider,
        "model": model,
        "request_method": request_method,
        "call_index": call_index,
        "attempt": attempt,
        "latency_ms": latency_ms,
        "failure_class": failure_class,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cost": cost,
        "currency": currency,
        "output_filter_action": output_filter_action,
        "output_filter_reason": output_filter_reason,
        "fallback": fallback,
        "segment_count": segment_count,
        "delivery_status": delivery_status,
        "sent_bubble_count": sent_bubble_count,
        "total_bubble_count": total_bubble_count,
    }
    for name, value in optional_values.items():
        if value is None:
            continue
        if name in {
            "provider",
            "model",
            "request_method",
            "failure_class",
            "output_filter_action",
            "output_filter_reason",
            "currency",
            "delivery_status",
        }:
            event[name] = _safe_code(value)
        elif name == "cost":
            event[name] = float(value)
        elif name == "fallback":
            event[name] = bool(value)
        else:
            event[name] = int(value)
    sent_hashes = _hash_many(sent_message_ids, key=hash_key)
    if sent_hashes:
        event["sent_message_id_hashes"] = sent_hashes
    return {key: value for key, value in event.items() if key in _EVENT_KEYS}


def _sanitize_event(event: dict[str, object]) -> dict[str, object]:
    sanitized = {key: event[key] for key in _EVENT_KEYS if key in event}
    shape = sanitized.get("shape")
    if isinstance(shape, dict):
        sanitized["shape"] = {key: shape[key] for key in _SHAPE_KEYS if key in shape}
    necessity = sanitized.get("necessity")
    if isinstance(necessity, dict):
        sanitized["necessity"] = {
            "score": int(necessity.get("score") or 0),
            "factors": [_safe_code(item) for item in necessity.get("factors", [])][:32]
            if isinstance(necessity.get("factors"), list)
            else [],
        }
    return sanitized


class TurnTelemetryWriter:
    def __init__(self, root: Path | None = None, *, instance_id: str | None = None):
        self.root = root or (plugin_data_dir("pb_webui", create=False) / _DEFAULT_ROOT_NAME)
        self.instance_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(instance_id or _default_instance_id()))[:80]
        self._key: bytes | None | object = _UNLOADED_KEY

    @property
    def hash_key(self) -> bytes | None:
        if self._key is _UNLOADED_KEY:
            self._key = self._load_key()
        return self._key if isinstance(self._key, bytes) else None

    def _key_path(self) -> Path:
        return self.root / _KEY_NAME

    def _load_key(self) -> bytes | None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._key_path()
            if path.is_file():
                value = path.read_bytes()
                return value if len(value) >= _KEY_SIZE else None
            value = secrets.token_bytes(_KEY_SIZE)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(path, flags, 0o600)
            try:
                os.write(fd, value)
            finally:
                os.close(fd)
            return value
        except Exception:
            return None

    def _event_path(self) -> Path:
        return self.root / f"turn_events-{_day_key()}-{self.instance_id}.jsonl"

    def _report_path(self, day_key: str) -> Path:
        return self.root / f"turn_report-{day_key}.json"

    def record(self, **fields: object) -> None:
        try:
            self.emit(build_turn_event(hash_key=self.hash_key, **fields))
        except Exception:
            self._log_failure()

    def emit(self, event: dict[str, object]) -> None:
        try:
            safe_event = _sanitize_event(event)
            if safe_event.get("stage") not in _STAGES or safe_event.get("decision") not in _DECISIONS:
                raise ValueError("invalid telemetry event")
            path = self._event_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(safe_event, ensure_ascii=False, separators=(",", ":"))
            with _LOCK:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            self._log_failure()

    def _log_failure(self) -> None:
        log_rate_limited(
            logger,
            "warning",
            "llm.turn_telemetry.failure",
            "LLM turn telemetry write failed; chat behavior is unchanged",
        )

    def report(self, day_key: str) -> dict[str, object]:
        turns: dict[str, list[dict[str, object]]] = defaultdict(list)
        try:
            paths = sorted(self.root.glob(f"turn_events-{day_key}-*.jsonl"))
        except Exception:
            paths = []
        for path in paths:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict) or not isinstance(row.get("turn_id"), str):
                    continue
                turns[row["turn_id"]].append(row)
        report = _build_report(turns, day_key=day_key)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._report_path(day_key).write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            self._log_failure()
        return report


_UNLOADED_KEY = object()


def _build_report(turns: dict[str, list[dict[str, object]]], *, day_key: str) -> dict[str, object]:
    shape_counts: Counter[str] = Counter()
    stage_decisions: dict[str, Counter[str]] = defaultdict(Counter)
    provider_attempts = 0
    provider_turns: set[str] = set()
    provider_success = 0
    provider_failed = 0
    latency_total = 0
    latency_count = 0
    token_totals: Counter[str] = Counter()
    cost_total = 0.0
    delivery_counts: Counter[str] = Counter()
    output_counts: Counter[str] = Counter()
    incomplete = 0
    missing_stages: Counter[str] = Counter()
    completed = 0
    for turn_id, events in turns.items():
        stages = {str(event.get("stage") or "") for event in events}
        ingress = next((event for event in events if event.get("stage") == "ingress"), None)
        if isinstance(ingress, dict):
            shape = ingress.get("shape")
            if isinstance(shape, dict):
                shape_counts[str(shape.get("len_bucket") or "unknown")] += 1
        for event in events:
            stage = str(event.get("stage") or "")
            decision = str(event.get("decision") or "")
            if stage and decision:
                stage_decisions[stage][decision] += 1
            if stage == "provider":
                provider_attempts += 1
                provider_turns.add(turn_id)
                if decision == "success":
                    provider_success += 1
                elif decision == "failed":
                    provider_failed += 1
                if isinstance(event.get("latency_ms"), (int, float)):
                    latency_total += int(event["latency_ms"])
                    latency_count += 1
                for name in ("prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens"):
                    if isinstance(event.get(name), (int, float)):
                        token_totals[name] += int(event[name])
                if isinstance(event.get("cost"), (int, float)):
                    cost_total += float(event["cost"])
            elif stage == "delivery":
                delivery_counts[str(event.get("delivery_status") or decision)] += 1
            elif stage == "output":
                action = str(event.get("output_filter_action") or decision)
                output_counts[action] += 1
        required = {"ingress", "output", "delivery"}
        missing = required - stages
        if missing:
            incomplete += 1
            for stage in missing:
                missing_stages[stage] += 1
        else:
            completed += 1
    return {
        "schema_version": _SCHEMA_VERSION,
        "day_key": day_key,
        "funnel": {
            "turns": len(turns),
            "completed": completed,
            "ingress": len(turns),
            "speak": len({
                turn_id for turn_id, events in turns.items() if any(event.get("stage") == "speak" for event in events)
            }),
            "reply_gate": len({
                turn_id
                for turn_id, events in turns.items()
                if any(event.get("stage") == "reply_gate" for event in events)
            }),
            "necessity": len({
                turn_id
                for turn_id, events in turns.items()
                if any(event.get("stage") == "necessity" for event in events)
            }),
            "provider": len(provider_turns),
            "output": len({
                turn_id for turn_id, events in turns.items() if any(event.get("stage") == "output" for event in events)
            }),
            "delivery": len({
                turn_id
                for turn_id, events in turns.items()
                if any(event.get("stage") == "delivery" for event in events)
            }),
        },
        "shape": {"len_bucket": dict(shape_counts)},
        "stages": {stage: dict(counter) for stage, counter in stage_decisions.items()},
        "provider": {
            "turns_called": len(provider_turns),
            "attempts": provider_attempts,
            "success": provider_success,
            "failed": provider_failed,
            "latency_ms_total": latency_total,
            "latency_ms_count": latency_count,
            "tokens": dict(token_totals),
            "cost": cost_total,
        },
        "output": dict(output_counts),
        "delivery": dict(delivery_counts),
        "incomplete_turns": incomplete,
        "missing_stages": dict(missing_stages),
    }


def record_turn_event(**fields: object) -> None:
    global _DEFAULT_WRITER  # noqa: PLW0603
    try:
        if _DEFAULT_WRITER is None:
            _DEFAULT_WRITER = TurnTelemetryWriter()
        _DEFAULT_WRITER.record(**fields)
    except Exception:
        log_rate_limited(
            logger,
            "warning",
            "llm.turn_telemetry.facade",
            "LLM turn telemetry was unavailable; chat behavior is unchanged",
        )


def reset_default_writer_for_tests() -> None:
    global _DEFAULT_WRITER  # noqa: PLW0603
    _DEFAULT_WRITER = None
