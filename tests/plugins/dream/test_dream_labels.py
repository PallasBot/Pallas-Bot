from src.plugins.dream.dream_labels import PSEUDO_SENDER_AT, pick_pseudo_sender_at


def test_pick_pseudo_sender_at_in_pool() -> None:
    for _ in range(30):
        s = pick_pseudo_sender_at()
        assert s in PSEUDO_SENDER_AT
        assert s.startswith("@")


def test_pool_nonempty() -> None:
    assert len(PSEUDO_SENDER_AT) >= 4
