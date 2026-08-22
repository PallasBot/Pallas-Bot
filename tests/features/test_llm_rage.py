from pallas.product.llm.rage import (
    RageState,
    calculate_attack_gain,
    calculate_silence_seconds,
    count_attack_tokens,
    decay_rage,
    evaluate_attack,
    rage_state_is_silenced,
)


def test_attack_gain_includes_tokens_pressure_and_current_rage() -> None:
    assert count_attack_tokens("你这个废物垃圾，闭嘴") == 3
    assert calculate_attack_gain(token_count=3, recent_count=2, rage=0) == 29
    assert calculate_attack_gain(token_count=3, recent_count=2, rage=100) == 30


def test_evaluate_attack_enters_silence_at_hysteresis_threshold() -> None:
    result = evaluate_attack(
        state=RageState(rage=70),
        user_text="你这个废物垃圾闭嘴",
        recent_attack_count=1,
        is_to_me=True,
        now=100,
        random_value=1.0,
    )

    assert result.rage == 100
    assert result.silenced_until == 100 + 600


def test_silence_duration_is_weighted_by_trigger_rage() -> None:
    assert calculate_silence_seconds(rage=75, random_value=1.0) == 60
    assert calculate_silence_seconds(rage=100, random_value=1.0) == 600


def test_decay_only_applies_after_a_complete_interval() -> None:
    state = RageState(rage=40, last_attack_at=100)

    assert decay_rage(state, now=159, interval_sec=60, step=10).rage == 40
    assert decay_rage(state, now=160, interval_sec=60, step=10).rage == 30


def test_silent_attack_does_not_change_state() -> None:
    state = RageState(rage=90, silenced_until=200)

    result = evaluate_attack(
        state=state,
        user_text="你这个废物",
        recent_attack_count=3,
        is_to_me=True,
        now=150,
        random_value=1.0,
    )

    assert result == state


def test_replayed_attack_message_does_not_change_state() -> None:
    state = RageState(rage=20, last_attack_message_id=9)

    result = evaluate_attack(
        state=state,
        user_text="你这个废物",
        recent_attack_count=1,
        is_to_me=True,
        now=150,
        random_value=1.0,
        message_id=9,
    )

    assert result == state


def test_silence_expires_below_the_hysteresis_boundary() -> None:
    assert rage_state_is_silenced(RageState(rage=90, silenced_until=200), now=199)
    assert not rage_state_is_silenced(RageState(rage=90, silenced_until=200), now=200)
