from __future__ import annotations


def parse_undercover_count(text: str, *, default: int) -> int:
    for token in (text or "").split():
        if token.isdigit():
            return max(1, min(3, int(token)))
    return default
