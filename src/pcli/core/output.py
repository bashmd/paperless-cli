"""Output adapters for json and ndjson contract modes."""

from __future__ import annotations

import json
from typing import Any

from pcli.core.errors import ErrorPayload


def render_success(
    *,
    resource: str,
    action: str,
    data: Any,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build success envelope for json format."""
    return {
        "ok": True,
        "resource": resource,
        "action": action,
        "data": data,
        "meta": meta or {},
    }


def render_error(payload: ErrorPayload) -> dict[str, Any]:
    """Build error envelope for json format."""
    return {
        "ok": False,
        "error": payload.as_dict(),
    }


def to_json(document: dict[str, Any]) -> str:
    """Serialize envelope dictionary to JSON."""
    return json.dumps(document, separators=(",", ":"), ensure_ascii=True)


def ndjson_item(record: dict[str, Any]) -> str:
    """Build NDJSON item line."""
    body = {**record, "type": "item"}
    return to_json(body)


def ndjson_error(payload: ErrorPayload) -> str:
    """Build NDJSON error line."""
    return to_json({"type": "error", "error": payload.as_dict()})


def ndjson_summary(*, next_cursor: str | None) -> str:
    """Build NDJSON summary line."""
    return to_json({"type": "summary", "meta": {"next_cursor": next_cursor}})
