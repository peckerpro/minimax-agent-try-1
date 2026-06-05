"""Tests for hello_agent.tools.response.ToolResponse."""
from __future__ import annotations

import json

from hello_agent.core.types import ToolResponse
from hello_agent.tools.response import ToolResponse as ResponseReexport


def test_response_module_reexports_core_type() -> None:
    """`tools.response.ToolResponse` must be the same class as `core.types.ToolResponse`."""
    assert ResponseReexport is ToolResponse


def test_ok_constructor_round_trip() -> None:
    """`ToolResponse.ok(data)` sets success=True and stores data unchanged."""
    payload = {"text": "hi", "n": 7}
    r = ToolResponse.ok(payload)
    assert r.success is True
    assert r.data == payload
    assert r.error is None
    assert r.hint is None


def test_fail_constructor_sets_error_and_hint() -> None:
    """`ToolResponse.fail(error, hint)` sets success=False and both error/hint."""
    r = ToolResponse.fail("oops", hint="try again later")
    assert r.success is False
    assert r.error == "oops"
    assert r.hint == "try again later"
    assert r.data is None


def test_from_exception_captures_typename_and_message() -> None:
    """`from_exception(exc)` formats as `TypeName: message` and is failure."""
    try:
        raise ValueError("kaboom")
    except ValueError as exc:
        r = ToolResponse.from_exception(exc)
    assert r.success is False
    assert r.error == "ValueError: kaboom"
    assert r.data is None


def test_to_json_is_valid_json_with_expected_keys() -> None:
    """`to_json()` returns a JSON string with success/data/error/hint keys."""
    r = ToolResponse.ok({"k": "v"})
    blob = r.to_json()
    parsed = json.loads(blob)
    assert parsed == {"success": True, "data": {"k": "v"}, "error": None, "hint": None}


def test_to_json_handles_non_jsonable_data_via_default_str() -> None:
    """`to_json()` falls back to `str()` for non-JSON-serializable data."""
    sentinel = object()
    r = ToolResponse.ok(sentinel)
    blob = r.to_json()
    parsed = json.loads(blob)
    assert parsed["success"] is True
    # `object.__str__` is "<object object at 0x...>"
    assert parsed["data"].startswith("<object object at")
