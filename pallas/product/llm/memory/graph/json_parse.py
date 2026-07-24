"""从 LLM 文本中解析 JSON（剥 markdown 围栏、取首个对象/数组）。"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    match = _FENCE_RE.match(raw)
    if match:
        return match.group(1).strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return raw


def _balanced_json_span(text: str) -> str | None:
    """从首个 `{` 或 `[` 起按括号配平切出一段。"""
    start = -1
    opener = ""
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            break
    if start < 0:
        return None
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:] if depth > 0 else None


def parse_llm_json(text: str) -> Any:
    """解析 LLM 输出中的 JSON 对象或数组。

    支持裸 JSON、```json 围栏、前后夹杂说明文字。
    无法解析时抛 ValueError。
    """
    cleaned = _strip_fences(text)
    if not cleaned:
        raise ValueError("empty llm json text")

    candidates: list[str] = [cleaned]
    span = _balanced_json_span(cleaned)
    if span and span not in candidates:
        candidates.insert(0, span)

    last_err: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_err = exc
            # 常见尾随逗号兜底
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError as exc2:
                last_err = exc2
                continue
        if isinstance(data, (dict, list)):
            return data
        last_err = ValueError(f"unexpected json type: {type(data).__name__}")

    raise ValueError(f"failed to parse llm json: {last_err}")
