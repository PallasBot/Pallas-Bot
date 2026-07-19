from pallas.product.llm.memory.inject import summarize_episode_notes


def test_summarize_episode_notes_dedupes_similar_prefixes() -> None:
    notes = [
        "群里一直把这个叫牛牛税",
        "群里一直把这个叫牛牛税，后来还延伸了",
        "上次大家约好周五再开一把",
        "某人总被拿这句梗调侃",
    ]
    out = summarize_episode_notes(notes, max_items=3)
    assert out == [
        "群里一直把这个叫牛牛税",
        "上次大家约好周五再开一把",
        "某人总被拿这句梗调侃",
    ]
