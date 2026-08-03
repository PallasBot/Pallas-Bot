from pallas.product.llm.speak_perception import clear_speak_perception_state, evaluate_speak_perception


def test_ambient_budget_blocks_second_opportunity() -> None:
    clear_speak_perception_state()
    common = {
        "plain_text": "这也太离谱了吧？",
        "aliases": [],
        "is_to_me": False,
        "ambient_rate": 1.0,
        "ambient_min_score": 0,
        "ambient_cooldown_sec": 0,
        "ambient_budget_limit": 1,
        "bot_id": 1,
        "group_id": 2,
        "now": 1000,
    }
    assert evaluate_speak_perception(**common).should_speak is True
    assert evaluate_speak_perception(**common).reason == "ambient_budget"
