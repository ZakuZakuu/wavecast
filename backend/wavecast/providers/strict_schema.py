"""Provider schema for strict structured output, derived from an application Pydantic schema.

The application keeps validating the full Pydantic model.  The vendor only receives the
structure it is asked to guarantee: types, enums, required properties, references and
nullable unions.  Keywords that constrain a value's length or range are dropped here and
stay enforced by Pydantic after the response arrives.

The conversion is deliberately conservative: a keyword or structure it has no explicit policy
for raises :class:`StrictSchemaUnsupportedError` before any request is made, instead of being
deleted and sent anyway.  It reads schema *keywords* only; property names such as ``title`` or
``default`` are business data and are never touched.
"""

from collections.abc import Mapping
from typing import Any

from .errors import ProviderConfigurationError


class StrictSchemaUnsupportedError(ProviderConfigurationError):
    """The application schema contains something the strict conversion has no policy for."""


# Pure annotations: they say nothing the model has to obey.
_ANNOTATIONS = frozenset({"title", "description", "default", "examples", "$comment"})
# Value constraints enforced by the application's own validation after the response.
_VALUE_CONSTRAINTS = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
    }
)
_DROPPED = _ANNOTATIONS | _VALUE_CONSTRAINTS
_KEPT_SCALAR = frozenset({"type", "enum", "const", "$ref"})
_SCHEMA_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


def to_strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new strict-mode schema; ``schema`` is never modified."""

    if schema.get("type") != "object" or not isinstance(schema.get("properties"), Mapping):
        raise StrictSchemaUnsupportedError("strict output needs an object schema at the root")
    return _node(schema, path="$")


def _node(schema: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise StrictSchemaUnsupportedError(f"{path}: schema node must be an object")
    result: dict[str, Any] = {}
    for keyword, value in schema.items():
        if keyword in _DROPPED:
            continue
        if keyword in _KEPT_SCALAR:
            result[keyword] = _scalar(keyword, value, path)
        elif keyword == "properties":
            result[keyword] = _properties(value, path)
        elif keyword == "$defs":
            if not isinstance(value, Mapping):
                raise StrictSchemaUnsupportedError(f"{path}: $defs must be an object")
            result[keyword] = {
                name: _node(definition, path=f"{path}/$defs/{name}")
                for name, definition in value.items()
            }
        elif keyword == "items":
            result[keyword] = _node(value, path=f"{path}/items")
        elif keyword == "anyOf":
            if not isinstance(value, list) or not value:
                raise StrictSchemaUnsupportedError(f"{path}: anyOf must be a non-empty list")
            result[keyword] = [_node(item, path=f"{path}/anyOf") for item in value]
        elif keyword == "required":
            continue  # rebuilt from the properties below
        elif keyword == "additionalProperties":
            if value is not False:
                raise StrictSchemaUnsupportedError(
                    f"{path}: free-form objects (additionalProperties) cannot be strict"
                )
        else:
            raise StrictSchemaUnsupportedError(f"{path}: keyword {keyword!r} has no strict policy")

    if result.get("type") == "object" or "properties" in result:
        properties = result.get("properties")
        if not isinstance(properties, dict):
            raise StrictSchemaUnsupportedError(f"{path}: free-form object cannot be strict")
        # Every property is required in strict mode.  Optional values stay optional by being
        # nullable (an ``anyOf`` with a null branch already is); nothing becomes non-null.
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result


def _properties(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StrictSchemaUnsupportedError(f"{path}: properties must be an object")
    return {name: _node(child, path=f"{path}/{name}") for name, child in value.items()}


def _scalar(keyword: str, value: Any, path: str) -> Any:
    if keyword == "type":
        types = value if isinstance(value, list) else [value]
        if not types or any(item not in _SCHEMA_TYPES for item in types):
            raise StrictSchemaUnsupportedError(f"{path}: unsupported type {value!r}")
        return list(value) if isinstance(value, list) else value
    if keyword == "$ref":
        if not isinstance(value, str) or not value.startswith("#/"):
            raise StrictSchemaUnsupportedError(f"{path}: only local $ref is supported")
        return value
    if keyword == "enum":
        if not isinstance(value, list) or not value:
            raise StrictSchemaUnsupportedError(f"{path}: enum must be a non-empty list")
        return list(value)
    return value  # const
