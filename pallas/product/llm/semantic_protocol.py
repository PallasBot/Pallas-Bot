"""低风险游戏协议响应：从「Bot 提示 → 真人短命令」中学习，独立于群表达画像。

协议不进入 profiles.json，也不参与行为/续句聚合；只复用 message 表与文件锁。
运行时仅当协议模板达到 3 次且 2 名真人、且满足定向与冷却时才自动回复。
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.fs_lock import interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

# 协议模板观察门槛：同一模板+命令至少 3 次、来自至少 2 名真人。
_PROTOCOL_MIN_COUNT = 3
_PROTOCOL_MIN_RESPONDERS = 2
# 协议独立冷却：每 bot × 群 10 分钟。
_PROTOCOL_COOLDOWN_SEC = 10 * 60
# 命令长度与安全边界。
_PROTOCOL_COMMAND_MIN_LEN = 2
_PROTOCOL_COMMAND_MAX_LEN = 16
_PROTOCOL_RISK_WORDS = (
    "管理",
    "权限",
    "付费",
    "转账",
    "绑定",
    "登录",
    "验证码",
    "删除",
    "退群",
    "禁言",
    "踢人",
    "封禁",
    "解封",
    "提现",
    "充值",
    "购买",
    "兑换",
    "口令",
    "密码",
)
# 显式命令候选：发送/回复「X」。
_PROTOCOL_COMMAND_RE = re.compile(r"(?:发送|回复)[「\"']([^「\"']{1,24})[」\"']")
# 昵称定向窗口：最近 3 分钟在该群发过消息的本地 Bot 才可响应昵称协议。
_PROTOCOL_RECENT_BOT_SEC = 3 * 60


class ProtocolObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    observation_id: str
    bot_id: int
    group_id: int
    trigger_template: str
    response_command: str
    responder_id: int
    source_message_id: int
    created_at: int


class ProtocolPattern(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bot_id: int
    trigger_template: str
    response_command: str
    count: int = 0
    responder_ids: list[int] = Field(default_factory=list)
    source_observation_ids: list[str] = Field(default_factory=list)
    updated_at: int = 0


def protocol_base_dir() -> Path:
    return plugin_data_dir("pb_webui", create=True) / "repeater_semantic_style"


def protocol_examples_path() -> Path:
    return protocol_base_dir() / "protocol_examples.jsonl"


def protocol_patterns_path() -> Path:
    return protocol_base_dir() / "protocol_patterns.json"


def protocol_cooldowns_path() -> Path:
    return protocol_base_dir() / "protocol_cooldowns.json"


def extract_protocol_commands(text: str) -> list[str]:
    """从 Bot 提示文本中提取显式短命令候选，去重保序。"""
    commands: list[str] = []
    for match in _PROTOCOL_COMMAND_RE.finditer(str(text or "")):
        command = str(match.group(1) or "").strip()
        if command and command not in commands:
            commands.append(command)
    return commands


def protocol_command_safe(command: str) -> bool:
    """命令必须短、自包含，且不含管理/资产/安全类风险词。"""
    text = str(command or "").strip()
    if not (_PROTOCOL_COMMAND_MIN_LEN <= len(text) <= _PROTOCOL_COMMAND_MAX_LEN):
        return False
    if re.search(r"[\r\n\0]", text):
        return False
    lowered = text.casefold()
    return not any(risk in lowered for risk in _PROTOCOL_RISK_WORDS)


def _load_observations() -> list[ProtocolObservation]:
    path = protocol_examples_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    observations: list[ProtocolObservation] = []
    for line in lines:
        try:
            observations.append(ProtocolObservation.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return observations


def _load_patterns() -> dict[tuple[int, str, str], ProtocolPattern]:
    try:
        raw = json.loads(protocol_patterns_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = raw.get("patterns") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return {}
    patterns: dict[tuple[int, str, str], ProtocolPattern] = {}
    for item in rows:
        try:
            pattern = ProtocolPattern.model_validate(item)
        except Exception:
            continue
        patterns[(pattern.bot_id, pattern.trigger_template, pattern.response_command)] = pattern
    return patterns


def _write_patterns(patterns: dict[tuple[int, str, str], ProtocolPattern]) -> None:
    path = protocol_patterns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"patterns": [item.model_dump(mode="json") for item in patterns.values()]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _normalize_template(text: str) -> str:
    """模板归一化：折叠空白、去掉命令候选占位，便于跨群聚合。"""
    normalized = re.sub(r"(?:发送|回复)[「\"'][^「\"']{1,24}[」\"']", "发送「命令」", str(text or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def record_protocol_observation(
    *,
    bot_id: int,
    group_id: int,
    trigger_text: str,
    reply_text: str,
    responder_id: int,
    source_message_id: int,
    created_at: int | None = None,
) -> bool:
    """记录一次「Bot 提示 → 真人短命令」观察；命令不在显式候选中则忽略。"""
    commands = extract_protocol_commands(trigger_text)
    reply = str(reply_text or "").strip()
    if reply not in commands or not protocol_command_safe(reply):
        return False
    template = _normalize_template(trigger_text)
    if not template:
        return False
    now = int(time.time()) if created_at is None else int(created_at)
    observation_id = f"{bot_id}:{group_id}:{source_message_id}:{reply}"
    with interprocess_file_lock(protocol_examples_path().with_suffix(".lock")):
        observations = _load_observations()
        if any(item.observation_id == observation_id for item in observations):
            return False
        observations.append(
            ProtocolObservation(
                observation_id=observation_id,
                bot_id=int(bot_id),
                group_id=int(group_id),
                trigger_template=template,
                response_command=reply,
                responder_id=int(responder_id),
                source_message_id=int(source_message_id),
                created_at=now,
            )
        )
        protocol_examples_path().parent.mkdir(parents=True, exist_ok=True)
        with protocol_examples_path().open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(observations[-1].model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n"
            )
        patterns = _load_patterns()
        key = (int(bot_id), template, reply)
        existing = patterns.get(key)
        if existing is None:
            existing = ProtocolPattern(
                bot_id=int(bot_id),
                trigger_template=template,
                response_command=reply,
                updated_at=now,
            )
        if responder_id not in existing.responder_ids:
            existing.responder_ids = [*existing.responder_ids, int(responder_id)][:8]
        if observation_id not in existing.source_observation_ids:
            existing.source_observation_ids = [*existing.source_observation_ids, observation_id][:8]
        existing.count += 1
        existing.updated_at = now
        patterns[key] = existing
        _write_patterns(patterns)
    return True


def _load_cooldowns() -> dict[tuple[int, int], int]:
    try:
        raw = json.loads(protocol_cooldowns_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[tuple[int, int], int] = {}
    for key, value in raw.items() if isinstance(raw, dict) else []:
        try:
            bot_id, group_id = (int(part) for part in str(key).split(":", 1))
            out[(bot_id, group_id)] = int(value)
        except (ValueError, TypeError):
            continue
    return out


def _write_cooldowns(cooldowns: dict[tuple[int, int], int]) -> None:
    path = protocol_cooldowns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {f"{bot_id}:{group_id}": sent_at for (bot_id, group_id), sent_at in cooldowns.items()}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def protocol_cooldown_ok(*, bot_id: int, group_id: int, now: int | None = None) -> bool:
    current = int(time.time()) if now is None else int(now)
    sent_at = _load_cooldowns().get((int(bot_id), int(group_id)), 0)
    return current - sent_at >= _PROTOCOL_COOLDOWN_SEC


def mark_protocol_sent(*, bot_id: int, group_id: int, now: int | None = None) -> None:
    current = int(time.time()) if now is None else int(now)
    with interprocess_file_lock(protocol_cooldowns_path().with_suffix(".lock")):
        cooldowns = _load_cooldowns()
        cooldowns[(int(bot_id), int(group_id))] = current
        _write_cooldowns(cooldowns)


def resolve_protocol_candidate(
    *,
    bot_id: int,
    group_id: int,
    trigger_text: str,
    recent_bot_id: int | None = None,
    now: int | None = None,
) -> str:
    """运行时判定：当前 Bot 提示是否命中合格协议模板，返回可自动回复的命令。

    ``recent_bot_id`` 为最近 3 分钟内该群最后发言的本地 Bot；昵称定向时仅
    当前 Bot 是最近发言者才允许响应。明确 @/引用由调用方在定向判定中处理。
    """
    commands = extract_protocol_commands(trigger_text)
    if not commands:
        return ""
    template = _normalize_template(trigger_text)
    if not template:
        return ""
    if not protocol_cooldown_ok(bot_id=bot_id, group_id=group_id, now=now):
        return ""
    patterns = _load_patterns()
    for command in commands:
        if not protocol_command_safe(command):
            continue
        pattern = patterns.get((int(bot_id), template, command))
        if pattern is None:
            continue
        if pattern.count < _PROTOCOL_MIN_COUNT or len(pattern.responder_ids) < _PROTOCOL_MIN_RESPONDERS:
            continue
        if recent_bot_id is not None and int(recent_bot_id) != int(bot_id):
            continue
        return command
    return ""


def protocol_status() -> dict[str, Any]:
    observations = _load_observations()
    patterns = _load_patterns()
    eligible = [
        pattern
        for pattern in patterns.values()
        if pattern.count >= _PROTOCOL_MIN_COUNT and len(pattern.responder_ids) >= _PROTOCOL_MIN_RESPONDERS
    ]
    return {
        "observation_count": len(observations),
        "pattern_count": len(patterns),
        "eligible_pattern_count": len(eligible),
    }


def clear_protocol_data_for_tests() -> None:
    for path in (protocol_examples_path(), protocol_patterns_path(), protocol_cooldowns_path()):
        try:
            path.unlink()
        except OSError:
            pass
