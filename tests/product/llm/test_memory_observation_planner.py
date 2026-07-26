from pallas.product.llm.memory.observation import (
    clear_observations_for_tests,
    dequeue_observations,
    list_observations,
    observation_queue_size,
    observe_message,
)
from pallas.product.llm.memory.planner import plan_memory_retrieval


def test_observation_queue_persists_pending_candidates(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.memory.observation._queue_path",
        lambda: tmp_path / "observation_queue.json",
    )
    clear_observations_for_tests()

    record = observe_message(
        bot_id=1,
        group_id=2,
        user_id=3,
        text="我们上次在群里聊过这个梗",
        source="message",
    )

    assert record.status == "pending"
    assert observation_queue_size() == 1
    assert [item.text for item in list_observations(group_id=2)] == [record.text]
    assert len(dequeue_observations(limit=1)) == 1
    assert observation_queue_size() == 0


def test_memory_planner_selects_social_channels() -> None:
    plan = plan_memory_retrieval("你还记得我们以前在群里的那个梗吗？谁和她关系好")

    assert plan.need_mid_term
    assert plan.need_episodes
    assert plan.need_person
    assert plan.need_relationship
    assert plan.need_graph
    assert plan.reasons
