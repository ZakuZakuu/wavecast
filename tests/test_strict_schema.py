"""The vendor schema is derived from the Pydantic one; the Pydantic model keeps validating."""

import copy
from datetime import datetime
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field
from wavecast.intelligence.models import RadioScript
from wavecast.models.dialogue import DialogueDraft
from wavecast.providers.strict_schema import StrictSchemaUnsupportedError, to_strict_schema


class Leaf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=20, description="a label")


class Sample(BaseModel):
    """Docstring becomes a description."""

    model_config = ConfigDict(extra="forbid")

    # Business properties that happen to be named like schema keywords.
    title: str = Field(min_length=1, max_length=50)
    default: int = Field(ge=0, le=9)
    kind: Literal["title", "default", "other"]
    tags: list[str] = Field(default_factory=list, max_length=12)
    note: str | None = Field(default=None, max_length=40)
    leaf: Leaf
    leaves: list[Leaf] = Field(min_length=1, max_length=3)


def _objects(schema: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found.extend(_objects(value))
    elif isinstance(schema, list):
        for item in schema:
            found.extend(_objects(item))
    return found


def test_value_constraints_and_annotations_are_dropped_but_structure_is_kept() -> None:
    strict = to_strict_schema(Sample.model_json_schema())

    flat = str(strict)
    for keyword in ("minLength", "maxLength", "maxItems", "minItems", "maximum", "minimum"):
        assert f"'{keyword}'" not in flat
    assert "'default':" not in flat.replace("'default': {'type'", "")  # keyword, not property
    assert strict["properties"]["kind"]["enum"] == ["title", "default", "other"]
    assert strict["properties"]["leaves"]["items"] == {"$ref": "#/$defs/Leaf"}
    assert strict["$defs"]["Leaf"]["properties"]["label"] == {"type": "string"}


def test_every_object_is_closed_and_requires_all_of_its_properties() -> None:
    strict = to_strict_schema(Sample.model_json_schema())

    objects = _objects(strict)
    assert len(objects) == 2
    for node in objects:
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])


def test_properties_named_like_keywords_survive() -> None:
    strict = to_strict_schema(Sample.model_json_schema())

    assert {"title", "default"} <= set(strict["properties"])
    assert strict["properties"]["title"] == {"type": "string"}
    assert strict["properties"]["default"] == {"type": "integer"}


def test_optional_values_stay_nullable_instead_of_becoming_non_null() -> None:
    strict = to_strict_schema(Sample.model_json_schema())

    assert strict["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert "note" in strict["required"]


def test_the_input_schema_is_not_modified() -> None:
    schema = Sample.model_json_schema()
    before = copy.deepcopy(schema)

    to_strict_schema(schema)

    assert schema == before


def test_strict_schema_is_a_view_the_pydantic_model_still_enforces() -> None:
    with pytest.raises(ValueError):
        Sample.model_validate_json(
            '{"title": "", "default": 1, "kind": "other", "tags": [], "note": null,'
            ' "leaf": {"label": "a"}, "leaves": [{"label": "a"}]}'
        )


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array", "items": {"type": "string"}},  # root must be an object
        {"type": "object", "properties": {"a": {"type": "string", "pattern": "^a"}}},
        {"type": "object", "properties": {"a": {"type": "string", "format": "date-time"}}},
        {"type": "object", "properties": {"a": {"oneOf": [{"type": "string"}, {"type": "null"}]}}},
        {"type": "object", "properties": {"a": {"type": "object"}}},  # free-form object
        {"type": "object", "properties": {"a": {"type": "object", "additionalProperties": True}}},
        {"type": "object", "properties": {"a": {"$ref": "http://elsewhere/x"}}},
        {"type": "object", "properties": {"a": {"type": "wrong"}}},
    ],
)
def test_structures_without_a_policy_fail_locally_instead_of_being_deleted(schema: dict) -> None:
    with pytest.raises(StrictSchemaUnsupportedError):
        to_strict_schema(schema)


def test_models_with_a_free_form_mapping_or_datetime_are_rejected() -> None:
    class WithMapping(BaseModel):
        data: dict[str, str]

    class WithTime(BaseModel):
        at: datetime

    for model in (WithMapping, WithTime):
        with pytest.raises(StrictSchemaUnsupportedError):
            to_strict_schema(model.model_json_schema())


def test_project_models_convert_locally() -> None:
    # Local conversion only: whether Ark accepts the full RadioScript schema is unverified.
    for model in (RadioScript, DialogueDraft):
        strict = to_strict_schema(model.model_json_schema())
        assert all(node["additionalProperties"] is False for node in _objects(strict))
