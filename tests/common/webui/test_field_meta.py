from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.common.webui.field_meta import field_kind_from_annotation, field_meta_for_model_field, literal_choices


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
