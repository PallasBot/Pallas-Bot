"""Short-lived per-user rage state and attack escalation rules."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pallas.product.llm.behavior import _DIRECT_ATTACK_TOKENS

RAGE_MAX = 100
SILENCE_THRESHOLD = 75
SILENCE_MIN_SEC = 60
SILENCE_MAX_SEC = 600


@dataclass(frozen=True, slots=True)
class RageState:
    rage: int = 0
    last_attack_at: int = 0
    last_attack_message_id: int = 0
    silenced_until: int = 0
    silence_reason: str = ""

    @property
    def is_silenced(self) -> bool:
        return self.silenced_until > 0


def count_attack_tokens(user_text: str) -> int:
    return sum(token in str(user_text or "") for token in _DIRECT_ATTACK_TOKENS)


def calculate_attack_gain(*, token_count: int, recent_count: int, rage: int) -> int:
    base = 8 + 5 * max(0, int(token_count)) + 3 * max(0, int(recent_count))
    gain = round(base * (1 + max(0, min(RAGE_MAX, int(rage))) / 125))
    return max(5, min(30, gain))


def calculate_silence_seconds(*, rage: int, random_value: float) -> int:
    current = max(SILENCE_THRESHOLD, min(RAGE_MAX, int(rage)))
    weight = ((current - SILENCE_THRESHOLD) / (RAGE_MAX - SILENCE_THRESHOLD)) ** 2
    max_seconds = SILENCE_MIN_SEC + (SILENCE_MAX_SEC - SILENCE_MIN_SEC) * weight
    value = max(0.0, min(1.0, float(random_value)))
    return int(round(SILENCE_MIN_SEC + (max_seconds - SILENCE_MIN_SEC) * value))


def decay_rage(state: RageState, *, now: int, interval_sec: int = 60, step: int = 5) -> RageState:
    if state.last_attack_at <= 0 or now < state.last_attack_at:
        return state
    intervals = (int(now) - state.last_attack_at) // max(1, int(interval_sec))
    if intervals <= 0:
        return state
    return replace(state, rage=max(0, state.rage - intervals * max(0, int(step))))


def evaluate_attack(
    *,
    state: RageState,
    user_text: str,
    recent_attack_count: int,
    is_to_me: bool,
    now: int,
    random_value: float,
    message_id: int = 0,
) -> RageState:
    if (
        state.silenced_until > int(now)
        or not is_to_me
        or (message_id > 0 and state.last_attack_message_id == int(message_id))
    ):
        return state
    token_count = count_attack_tokens(user_text)
    if token_count == 0:
        return state
    current = decay_rage(state, now=now)
    gain = calculate_attack_gain(token_count=token_count, recent_count=recent_attack_count, rage=current.rage)
    rage = min(RAGE_MAX, current.rage + gain)
    silence_seconds = 0
    if rage >= SILENCE_THRESHOLD:
        silence_seconds = calculate_silence_seconds(rage=rage, random_value=random_value)
    return replace(
        current,
        rage=rage,
        last_attack_at=int(now),
        last_attack_message_id=int(message_id),
        silenced_until=int(now) + silence_seconds,
        silence_reason="direct_attack" if silence_seconds else "",
    )


def rage_state_is_silenced(state: RageState, *, now: int) -> bool:
    return int(state.silenced_until) > int(now)
