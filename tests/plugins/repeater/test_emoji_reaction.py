import time


def test_sent_reactions_bounded():
    from src.plugins.repeater.emoji_reaction import (
        SENT_REACTIONS_MAX_SIZE,
        mark_reaction_sent,
        sent_reactions,
    )

    bot_id = "test_bot_bound"
    try:
        for i in range(SENT_REACTIONS_MAX_SIZE + 5000):
            mark_reaction_sent(bot_id, i)

        assert len(sent_reactions[bot_id]) <= SENT_REACTIONS_MAX_SIZE
    finally:
        sent_reactions.pop(bot_id, None)


def test_sent_reactions_keeps_recent():
    from src.plugins.repeater.emoji_reaction import (
        mark_reaction_sent,
        sent_reactions,
    )

    bot_id = "test_bot_recent"
    try:
        for i in range(15000):
            mark_reaction_sent(bot_id, i)

        remaining = sent_reactions[bot_id]
        timestamps = list(remaining.values())
        assert timestamps == sorted(timestamps)
    finally:
        sent_reactions.pop(bot_id, None)
