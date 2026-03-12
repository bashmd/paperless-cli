"""Tests for output envelope and ndjson adapters."""

from __future__ import annotations

import json

from pcli.core.errors import ErrorPayload
from pcli.core.output import (
    ndjson_error,
    ndjson_item,
    ndjson_summary,
    render_error,
    render_success,
)


def test_render_success_envelope_shape() -> None:
    payload = render_success(
        resource="docs",
        action="get",
        data={"id": 1},
        meta={"page_count": 2},
    )
    assert payload == {
        "ok": True,
        "resource": "docs",
        "action": "get",
        "data": {"id": 1},
        "meta": {"page_count": 2},
    }


def test_render_error_envelope_shape() -> None:
    payload = render_error(
        ErrorPayload(
            code="AUTH_INVALID_TOKEN",
            message="Token rejected by Paperless",
            details={},
        )
    )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "AUTH_INVALID_TOKEN"


def test_ndjson_records_are_typed() -> None:
    item = json.loads(ndjson_item({"id": 1}))
    error = json.loads(
        ndjson_error(
            ErrorPayload(
                code="ANY_ERROR",
                message="Anything failed",
                details={},
            )
        )
    )
    summary = json.loads(ndjson_summary(next_cursor=None))
    assert item["type"] == "item"
    assert error["type"] == "error"
    assert summary["type"] == "summary"
    assert summary["meta"]["next_cursor"] is None


def test_ndjson_item_type_cannot_be_overridden() -> None:
    item = json.loads(ndjson_item({"type": "broken", "id": 5}))
    assert item["type"] == "item"
