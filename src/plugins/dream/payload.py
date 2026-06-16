from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any


@dataclass
class DriftPayload:
    nickname: str
    text: str | None = None
    image_bytes: bytes | None = None


def drift_payload_to_dict(payload: DriftPayload) -> dict[str, Any]:
    if not isinstance(payload, DriftPayload):
        raise TypeError("payload must be DriftPayload")
    out: dict[str, Any] = {"nickname": str(payload.nickname or "")}
    if payload.text:
        out["text"] = str(payload.text)
    if payload.image_bytes:
        out["image_b64"] = base64.b64encode(payload.image_bytes).decode("ascii")
    return out


def drift_payload_from_dict(data: dict[str, Any]) -> DriftPayload:
    nick = str(data.get("nickname") or "").strip() or "某位博士"
    text = data.get("text")
    text_out = str(text) if isinstance(text, str) and text else None
    image_b64 = data.get("image_b64")
    image_bytes = None
    if isinstance(image_b64, str) and image_b64:
        try:
            image_bytes = base64.b64decode(image_b64.encode("ascii"))
        except Exception:
            image_bytes = None
    return DriftPayload(nickname=nick, text=text_out, image_bytes=image_bytes)
