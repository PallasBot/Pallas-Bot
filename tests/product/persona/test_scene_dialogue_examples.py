from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.pb_webui.llm_ops_api import register_llm_ops_router
from pallas.product.persona.scene_dialogue_examples import (
    SceneDialogueExample,
    create_scene_dialogue_example,
    list_scene_dialogue_examples,
    select_scene_dialogue_examples_for_turn,
)


def test_example_validation_rejects_overlong_fields() -> None:
    try:
        SceneDialogueExample(
            example_id="scene-example-1",
            bot_id=1,
            scene="banter",
            user_cue="x" * 121,
            positive="短回",
            negative="长回",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("expected bounded user cue validation")


def test_storage_and_selector_keep_enabled_scene_relevant_subset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    selected = create_scene_dialogue_example(
        bot_id=42,
        scene="接梗玩笑",
        user_cue="这个梗太好笑了",
        positive="顺着梗短接一句，例如：笑死，这个确实有点狠。",
        negative="不要只回行行行，也不要解释笑点。",
    )
    create_scene_dialogue_example(
        bot_id=42,
        scene="venting",
        user_cue="今天加班好累",
        positive="先接住情绪，再简短回应。",
        negative="不要强行打趣。",
    )
    disabled = create_scene_dialogue_example(
        bot_id=42,
        scene="banter",
        user_cue="这个梗太好笑了",
        positive="这条不会被选中。",
        negative="不要出现。",
        enabled=False,
    )

    assert selected.scene == "banter"
    assert len(list_scene_dialogue_examples(42)) == 3
    assert [
        item.example_id
        for item in select_scene_dialogue_examples_for_turn(42, scene="banter", user_text="这个梗真的好笑", limit=1)
    ] == [selected.example_id]
    assert disabled.example_id not in {
        item.example_id
        for item in select_scene_dialogue_examples_for_turn(42, scene="banter", user_text="这个梗真的好笑")
    }


def test_selector_returns_empty_for_no_data_or_disabled_examples(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    assert select_scene_dialogue_examples_for_turn(42, scene="banter", user_text="你好") == []


def test_selector_skips_same_scene_example_without_cue_relevance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    create_scene_dialogue_example(
        bot_id=42,
        scene="banter",
        user_cue="这个梗太好笑了",
        positive="顺着梗短接。",
        negative="不要只回行行行。",
    )

    assert select_scene_dialogue_examples_for_turn(42, scene="banter", user_text="今晚吃什么") == []


def test_management_api_handles_empty_create_update_and_delete(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    app = FastAPI()
    router = APIRouter()
    register_llm_ops_router(
        router, x="/pallas/api", plugin_config=object(), check_write_token=lambda *_args, **_kwargs: None
    )
    app.include_router(router)
    client = TestClient(app)

    assert client.get("/pallas/api/common-config/llm/persona/scene-dialogue-examples", params={"bot_id": 42}).json()[
        "data"
    ] == {
        "items": [],
        "count": 0,
    }
    created = client.post(
        "/pallas/api/common-config/llm/persona/scene-dialogue-examples",
        json={
            "bot_id": 42,
            "scene": "banter",
            "user_cue": "这个梗太好笑了",
            "positive": "顺着梗短接。",
            "negative": "不要只回行行行。",
        },
    ).json()["data"]
    assert (
        client.put(
            f"/pallas/api/common-config/llm/persona/scene-dialogue-examples/{created['example_id']}",
            json={"enabled": False},
        ).json()["data"]["enabled"]
        is False
    )
    assert (
        client.delete(
            f"/pallas/api/common-config/llm/persona/scene-dialogue-examples/{created['example_id']}"
        ).status_code
        == 200
    )
