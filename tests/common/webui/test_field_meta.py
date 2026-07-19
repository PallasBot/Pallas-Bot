from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pallas.console.webui.field_meta import (
    field_kind_from_annotation,
    field_meta_for_model_field,
    is_multiline_field,
    is_secret_field,
    literal_choices,
    numeric_bounds,
)


def test_literal_choices():
    assert literal_choices(Literal["auto", "session", "fleet"]) == ["auto", "session", "fleet"]


def test_field_kind_enum():
    assert field_kind_from_annotation(Literal["a", "b"]) == "enum"


class _M(BaseModel):
    mode: Literal["auto", "session"] = Field(default="auto", description="test")


def test_field_meta_includes_choices():
    f = _M.model_fields["mode"]
    row = field_meta_for_model_field(
        key="mode",
        field=f,
        env_key="MODE",
        cur="auto",
        default_value="auto",
    )
    assert row["kind"] == "enum"
    assert row["choices"] == ["auto", "session"]


def test_field_meta_normalizes_legacy_description():
    class _Legacy(BaseModel):
        x: int = Field(default=1, description="群内复读触发次数。")

    f = _Legacy.model_fields["x"]
    row = field_meta_for_model_field(
        key="x",
        field=f,
        env_key="X",
        cur=1,
        default_value=1,
    )
    assert row["description"].startswith("用途：")
    assert "填写：" in row["description"]


def test_field_meta_keeps_field_help_description():
    from pallas.console.webui.field_help import field_help

    class _Help(BaseModel):
        y: bool = Field(
            default=False,
            description=field_help("是否启用", "选 true 或 false"),
        )

    f = _Help.model_fields["y"]
    row = field_meta_for_model_field(
        key="y",
        field=f,
        env_key="Y",
        cur=False,
        default_value=False,
    )
    assert row["description"] == field_help("是否启用", "选 true 或 false")


def test_field_meta_includes_choice_labels_for_registered_enum():
    class _Mode(BaseModel):
        llm_repeater_mode: Literal["off", "select", "select_polish_lite"] = Field(default="select")

    f = _Mode.model_fields["llm_repeater_mode"]
    row = field_meta_for_model_field(
        key="llm_repeater_mode",
        field=f,
        env_key="LLM_REPEATER_MODE",
        cur="select",
        default_value="select",
    )
    assert row["choice_labels"]["select"] == "命中语料时 AI 选句（推荐）"
    assert row["choice_labels"]["off"] == "关闭 AI 接话"
    assert row["choice_labels"]["select_polish_lite"] == "选句为主，少数回复轻润色"


def test_field_meta_includes_choice_labels_for_llm_vector_retrieve():
    class _Retrieve(BaseModel):
        llm_vector_retrieve: Literal["keyword", "hybrid", "embedding"] = Field(default="keyword")

    f = _Retrieve.model_fields["llm_vector_retrieve"]
    row = field_meta_for_model_field(
        key="llm_vector_retrieve",
        field=f,
        env_key="LLM_VECTOR_RETRIEVE",
        cur="keyword",
        default_value="keyword",
    )
    assert row["choice_labels"]["hybrid"] == "关键词 + 向量（推荐）"
    assert row["choice_labels"]["keyword"] == "仅关键词（默认）"


class _Bounds(BaseModel):
    port: int = Field(default=9099, ge=1, le=65535)
    rate: float = Field(default=0.5, gt=0.0, lt=1.0)
    loose: int = Field(default=3)


def test_numeric_bounds_ge_le():
    assert numeric_bounds(_Bounds.model_fields["port"]) == (1.0, 65535.0)


def test_numeric_bounds_gt_lt():
    assert numeric_bounds(_Bounds.model_fields["rate"]) == (0.0, 1.0)


def test_numeric_bounds_absent():
    assert numeric_bounds(_Bounds.model_fields["loose"]) == (None, None)


def test_field_meta_int_bounds_are_int():
    row = field_meta_for_model_field(
        key="port",
        field=_Bounds.model_fields["port"],
        env_key="PORT",
        cur=9099,
        default_value=9099,
    )
    assert row["min_value"] == 1
    assert isinstance(row["min_value"], int)
    assert row["max_value"] == 65535
    assert isinstance(row["max_value"], int)


def test_field_meta_float_bounds_are_float():
    row = field_meta_for_model_field(
        key="rate",
        field=_Bounds.model_fields["rate"],
        env_key="RATE",
        cur=0.5,
        default_value=0.5,
    )
    assert row["min_value"] == 0.0
    assert isinstance(row["min_value"], float)
    assert row["max_value"] == 1.0


def test_field_meta_no_bounds_key_when_absent():
    row = field_meta_for_model_field(
        key="loose",
        field=_Bounds.model_fields["loose"],
        env_key="LOOSE",
        cur=3,
        default_value=3,
    )
    assert "min_value" not in row
    assert "max_value" not in row


class _Secret(BaseModel):
    api_key: str = Field(default="")
    explicit: str = Field(default="", json_schema_extra={"secret": True})
    opt_out: str = Field(default="my_token", json_schema_extra={"secret": False})
    nickname: str = Field(default="")
    note: str = Field(default="", json_schema_extra={"multiline": True})


def test_is_secret_name_heuristic():
    assert is_secret_field("api_key", "X_API_KEY", _Secret.model_fields["api_key"]) is True
    assert is_secret_field("nickname", "NICKNAME", _Secret.model_fields["nickname"]) is False


def test_is_secret_explicit_extra():
    assert is_secret_field("explicit", "EXPLICIT", _Secret.model_fields["explicit"]) is True


def test_is_secret_explicit_opt_out_overrides_name():
    # 名称含 token 但显式 secret=False，应尊重显式声明
    assert is_secret_field("opt_out", "OPT_OUT", _Secret.model_fields["opt_out"]) is False


def test_field_meta_marks_secret_string():
    row = field_meta_for_model_field(
        key="api_key",
        field=_Secret.model_fields["api_key"],
        env_key="API_KEY",
        cur="",
        default_value="",
    )
    assert row["kind"] == "string"
    assert row["secret"] is True


def test_field_meta_multiline_flag():
    assert is_multiline_field(_Secret.model_fields["note"]) is True
    row = field_meta_for_model_field(
        key="note",
        field=_Secret.model_fields["note"],
        env_key="NOTE",
        cur="",
        default_value="",
    )
    assert row["multiline"] is True


class _UiGroup(BaseModel):
    timeout_sec: int = Field(default=30, json_schema_extra={"ui_group": "高级", "ui_order": 10, "ui_hidden": True})


def test_field_meta_json_schema_ui_hints():
    f = _UiGroup.model_fields["timeout_sec"]
    row = field_meta_for_model_field(
        key="timeout_sec",
        field=f,
        env_key="TIMEOUT_SEC",
        cur=30,
        default_value=30,
    )
    assert row["ui_group"] == "高级"
    assert row["ui_order"] == 10
    assert row["ui_hidden"] is True
