from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DriftPayload:
    nickname: str
    text: str | None = None
    image_bytes: bytes | None = None
