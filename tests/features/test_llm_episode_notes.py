from pallas.product.llm.memory.inject import format_memory_blocks, summarize_episode_notes


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


def test_format_memory_blocks_separates_event_ip_and_teach() -> None:
    block = format_memory_blocks(
        [
            {"source": "auto_episode_summary", "content": "群友约定周五晚上开黑"},
            {"source": "auto_ip_knowledge", "content": "鸣潮声骸可自由切换"},
            {"source": "teach", "content": "阿灿希望被叫作阿灿"},
        ],
        max_len=200,
    )

    assert "【用户明确教导】" in block
    assert "【已确认群事件】" in block
    assert "【相关 IP 知识】" in block
    assert block.index("【用户明确教导】") < block.index("【已确认群事件】") < block.index("【相关 IP 知识】")
