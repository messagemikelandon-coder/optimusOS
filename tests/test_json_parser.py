from __future__ import annotations

import pytest

from app.services.openai_web import parse_json_object


def test_parses_plain_json() -> None:
    assert parse_json_object('{"value": 1}') == {"value": 1}


def test_parses_fenced_json() -> None:
    assert parse_json_object('```json\n{"value": 2}\n```') == {"value": 2}


def test_extracts_json_from_surrounding_text() -> None:
    assert parse_json_object('Result: {"value": 3} done') == {"value": 3}


def test_rejects_array() -> None:
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")
