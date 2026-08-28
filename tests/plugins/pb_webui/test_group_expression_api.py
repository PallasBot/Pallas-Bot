from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from packages.pb_webui.common_config_api import register_common_config_router
from packages.pb_webui.config import Config
from packages.pb_webui.llm_ops_api import register_llm_ops_router
from packages.pb_webui.llm_product_api import register_llm_product_router


def test_group_expression_openapi_uses_unified_profile_shape() -> None:
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)

    operation = app.openapi()["paths"]["/pallas/api/common-config/llm/persona/group-style"]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("_ApiOkResponse_GroupExpressionProfile_")
    assert {item["name"] for item in operation["parameters"]} == {"bot_id", "group_id", "scene"}


def test_semantic_style_examples_openapi_uses_limited_read_contract() -> None:
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)

    operation = app.openapi()["paths"]["/pallas/api/common-config/llm/persona/semantic-style-examples"]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("_ApiOkResponse__SemanticStyleExamplesData_")
    assert {item["name"] for item in operation["parameters"]} == {"bot_id", "group_id", "scene", "limit"}


@pytest.mark.asyncio
async def test_semantic_style_examples_returns_scoped_limited_content(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style

    example = repeater_semantic_style.SemanticStyleExample(
        example_id="42:100:7",
        created_at=100,
        bot_id=7,
        group_id=42,
        scene="group_chat",
        trigger_text="前句",
        reply_text="接话",
        label=repeater_semantic_style.SemanticStyleLabel(
            interaction_actions=["echo"],
            semantic_relations=["同意"],
            intensity="soft",
            forms=["短句"],
            is_reply_pair=True,
            transferable=True,
        ),
        source_kind="human_pair",
        trigger_user_id=123,
        reply_user_id=456,
        pair_relation="quoted",
        behavior_strategy=repeater_semantic_style.BehaviorStrategy(
            scene="轻松闲聊",
            action="接住前句",
            outcome="保持互动",
            learning_type="observed",
            count=2,
        ),
    )
    monkeypatch.setattr(
        repeater_semantic_style,
        "list_semantic_style_examples",
        lambda **kwargs: [example],
    )
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/pallas/api/common-config/llm/persona/semantic-style-examples",
            params={"bot_id": 7, "group_id": 42, "limit": 1},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"] == [
        {
            "example_id": "42:100:7",
            "created_at": 100,
            "pair_relation": "quoted",
            "trigger_text": "前句",
            "reply_text": "接话",
            "learning_type": "observed",
            "label": {
                "interaction_actions": ["echo"],
                "semantic_relations": ["同意"],
                "intensity": "soft",
                "forms": ["短句"],
            },
            "behavior_strategy": {
                "scene": "轻松闲聊",
                "action": "接住前句",
                "outcome": "保持互动",
                "learning_type": "observed",
                "count": 2,
            },
        }
    ]
    assert "trigger_user_id" not in data["items"][0]
    assert "reply_user_id" not in data["items"][0]


def test_semantic_style_examples_marks_bot_reply_as_self_reflection() -> None:
    from packages.pb_webui.llm_ops_api import semantic_style_examples_response_data
    from pallas.product.llm import repeater_semantic_style

    example = repeater_semantic_style.SemanticStyleExample(
        example_id="42:101:7",
        created_at=101,
        bot_id=7,
        group_id=42,
        scene="group_chat",
        trigger_text="前句",
        reply_text="牛牛接话",
        label=repeater_semantic_style.SemanticStyleLabel(is_reply_pair=True, transferable=True),
        source_kind="human_pair",
        bot_style_positive=True,
        behavior_strategy=repeater_semantic_style.BehaviorStrategy(
            scene="相似场景",
            action="接住话题",
            outcome="继续互动",
            learning_type="observed",
        ),
    )

    item = semantic_style_examples_response_data([example])["items"][0]

    assert item["learning_type"] == "self_reflection"
    assert item["behavior_strategy"]["learning_type"] == "self_reflection"


@pytest.mark.asyncio
async def test_group_expression_merges_legacy_and_exact_semantic_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style

    class GroupRepo:
        async def get(self, group_id: int):
            assert group_id == 42
            return type("Group", (), {"style_profile": {"sample": {"message_count": 40, "answer_count": 8}}})()

    semantic_profile = repeater_semantic_style.SemanticStyleProfile(
        bot_id=100,
        group_id=42,
        scene="group_chat",
        direct_examples=["直接样本"],
        direct_pairs=[{"trigger_text": "问", "reply_text": "答"}],
        rewrite_seeds=["改写样本"],
        intensity_counts={"soft": 2},
        form_counts={"question": 1},
        bubble_counts=[1, 2, 2],
        segment_char_lengths=[2, 4, 6],
        rhythm_counts={"single": 1, "multi": 2},
        sample_count=3,
        updated_at=100,
    )
    monkeypatch.setattr("pallas.core.foundation.db.make_group_config_repository", lambda: GroupRepo())
    refresh_calls: list[bool] = []
    monkeypatch.setattr(
        repeater_semantic_style,
        "refresh_semantic_style_cache",
        lambda *, force=False: refresh_calls.append(force),
    )
    monkeypatch.setattr(
        repeater_semantic_style,
        "cached_semantic_style_profile",
        lambda bot_id, group_id, scene: (
            semantic_profile if (bot_id, group_id, scene) == (100, 42, "group_chat") else None
        ),
    )
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/pallas/api/common-config/llm/persona/group-style",
            params={"bot_id": 100, "group_id": 42},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["aggregate"]["message_count"] == 40
    assert data["aggregate"]["answer_count"] == 8
    assert data["examples_summary"]["direct_example_count"] == 1
    assert data["examples_summary"]["direct_pair_count"] == 1
    assert data["examples_summary"]["rewrite_seed_count"] == 1
    assert data["examples_summary"]["intensity_counts"] == {"soft": 2}
    assert data["examples_summary"]["form_counts"] == {"question": 1}
    assert data["reply_shape"]["bubble_count_p50"] == 0
    assert data["reply_shape"]["bubble_count_p90"] == 0
    assert data["reply_shape"]["segment_char_length_p50"] == 0
    assert data["reply_shape"]["segment_char_length_p90"] == 0
    assert data["reply_shape"]["rhythm_distribution"] == {}
    assert refresh_calls == [False]


@pytest.mark.asyncio
async def test_group_expression_without_bot_id_returns_aggregate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style

    class GroupRepo:
        async def get(self, group_id: int):
            return type("Group", (), {"style_profile": {"sample": {"message_count": 12}}})()

    monkeypatch.setattr("pallas.core.foundation.db.make_group_config_repository", lambda: GroupRepo())
    monkeypatch.setattr(
        repeater_semantic_style,
        "refresh_semantic_style_cache",
        lambda **kwargs: pytest.fail("aggregate-only request must not refresh semantic cache"),
    )
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/pallas/api/common-config/llm/persona/group-style",
            params={"group_id": 42},
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["aggregate"]["message_count"] == 12
    assert response.json()["data"]["examples_summary"] == {
        "profile_ref": "",
        "scene": "",
        "sample_count": 0,
        "direct_example_count": 0,
        "direct_pair_count": 0,
        "rewrite_seed_count": 0,
        "intensity_counts": {},
        "form_counts": {},
        "updated_at": None,
    }


@pytest.mark.asyncio
async def test_group_expression_rejects_invalid_scope_and_contains_repository_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRepo:
        async def get(self, group_id: int):
            raise RuntimeError("repository unavailable")

    monkeypatch.setattr("pallas.core.foundation.db.make_group_config_repository", lambda: BrokenRepo())
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.get("/pallas/api/common-config/llm/persona/group-style", params={"group_id": 0})
        failed = await client.get("/pallas/api/common-config/llm/persona/group-style", params={"group_id": 42})

    assert invalid.status_code == 422
    assert failed.status_code == 500
    assert failed.json() == {"detail": "repository unavailable"}


def test_semantic_style_manage_openapi_has_typed_actions() -> None:
    app = FastAPI()
    register_llm_product_router(app.router, x="/pallas/api", plugin_config=Config())

    schema = app.openapi()
    operation = schema["paths"]["/pallas/api/llm/repeater-semantic-style/manage"]["post"]
    body_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    body_schema = schema["components"]["schemas"][body_ref.rsplit("/", 1)[-1]]

    assert set(body_schema["properties"]["action"]["enum"]) == {
        "status",
        "direct_enabled",
        "clear",
        "rebuild",
        "quality",
        "recover",
        "disable",
        "enable",
        "set_governance",
    }
    assert body_schema["additionalProperties"] is False
    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    response_schema = schema["components"]["schemas"][response_ref.rsplit("/", 1)[-1]]
    data_schema = response_schema["properties"]["data"]
    assert any(item.get("$ref", "").endswith("_SemanticStyleQualityData") for item in data_schema["anyOf"])


def test_persona_observe_openapi_exposes_account_profile() -> None:
    app = FastAPI()
    register_common_config_router(app.router, x="/pallas/api", plugin_config=Config())

    schema = app.openapi()
    operation = schema["paths"]["/pallas/api/common-config/llm/persona-observe"]["get"]
    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]

    assert response_ref.endswith("_ApiOkResponse__PersonaObserveData_")
    assert "AccountPersonaProfile" in schema["components"]["schemas"]


def test_sticker_label_openapi_uses_typed_global_contracts() -> None:
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)

    schema = app.openapi()
    overview = schema["paths"]["/pallas/api/common-config/llm/persona/sticker-labels"]["get"]
    overview_ref = overview["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert overview_ref.endswith("_ApiOkResponse__StickerLabelOverviewData_")

    manage = schema["paths"]["/pallas/api/common-config/llm/persona/sticker-labels/manage"]["post"]
    body_schema = manage["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema["discriminator"]["propertyName"] == "action"
    assert {item["$ref"].rsplit("/", 1)[-1] for item in body_schema["oneOf"]} == {
        "_StickerLabelRequeueBody",
        "_StickerLabelPauseBody",
        "_StickerLabelClearBody",
    }

    response_ref = manage["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    response_schema = schema["components"]["schemas"][response_ref.rsplit("/", 1)[-1]]
    assert {item["$ref"].rsplit("/", 1)[-1] for item in response_schema["properties"]["data"]["anyOf"]} == {
        "_StickerLabelRequeueResult",
        "_StickerLabelPauseResult",
        "_StickerLabelClearResult",
    }


@pytest.mark.asyncio
async def test_sticker_label_observability_and_maintenance_are_global(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_observability

    overview = {
        "labels": {"total": 7, "sticker": 5, "not_sticker": 2, "current_version": 6, "low_confidence": 1},
        "jobs": {"pending": 2, "failed": 1, "recent_errors": [{"job_id": "bad", "error": "timeout"}]},
        "lazy_labels_paused": False,
        "label_circuit_open": False,
        "vlm_refine_avoided": 3,
        "vlm_refine_actual": 4,
        "send_hits": 2,
    }
    monkeypatch.setattr(
        sticker_label_observability,
        "build_sticker_label_overview",
        pytest.importorskip("unittest.mock").AsyncMock(return_value=overview),
    )
    requeue = pytest.importorskip("unittest.mock").AsyncMock(
        return_value={"requeued": 2, "queued": 2, "skipped": 1, "missing_cache": 1}
    )
    monkeypatch.setattr(sticker_label_observability, "requeue_stale_sticker_labels", requeue)
    monkeypatch.setattr(sticker_label_observability, "set_lazy_sticker_labels_paused", lambda paused: paused)
    clear = pytest.importorskip("unittest.mock").AsyncMock(return_value=True)
    monkeypatch.setattr(sticker_label_observability, "clear_sticker_label", clear)

    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=lambda *a, **k: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        stats = await client.get("/pallas/api/common-config/llm/persona/sticker-labels")
        requeued = await client.post(
            "/pallas/api/common-config/llm/persona/sticker-labels/manage", json={"action": "requeue"}
        )
        paused = await client.post(
            "/pallas/api/common-config/llm/persona/sticker-labels/manage", json={"action": "pause", "paused": True}
        )
        cleared = await client.post(
            "/pallas/api/common-config/llm/persona/sticker-labels/manage",
            json={"action": "clear", "content_hash": "a" * 64},
        )
        requeue_with_pause = await client.post(
            "/pallas/api/common-config/llm/persona/sticker-labels/manage",
            json={"action": "requeue", "paused": True},
        )
        pause_without_value = await client.post(
            "/pallas/api/common-config/llm/persona/sticker-labels/manage", json={"action": "pause"}
        )
        clear_uppercase_hash = await client.post(
            "/pallas/api/common-config/llm/persona/sticker-labels/manage",
            json={"action": "clear", "content_hash": "A" * 64},
        )

    assert stats.json()["data"] == overview
    assert requeued.json()["data"] == {"requeued": 2, "queued": 2, "skipped": 1, "missing_cache": 1}
    requeue.assert_awaited_once()
    assert paused.json()["data"] == {"lazy_labels_paused": True}
    clear.assert_awaited_once_with("a" * 64)
    assert cleared.json()["data"] == {"cleared": True}
    assert requeue_with_pause.status_code == 422
    assert pause_without_value.status_code == 422
    assert clear_uppercase_hash.status_code == 422
