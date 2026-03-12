"""Opaque cursor encoding/validation helpers."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from pcli.core.errors import UsageValidationError

_CURSOR_VERSION = 1


@dataclass(slots=True, frozen=True)
class CursorState:
    """Decoded cursor state."""

    command: str
    signature: dict[str, Any]
    offset: int


def encode_cursor(*, command: str, signature: dict[str, Any], offset: int) -> str:
    """Encode cursor payload into an opaque URL-safe token."""
    payload = {
        "v": _CURSOR_VERSION,
        "cmd": command,
        "sig": signature,
        "offset": offset,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> CursorState:
    """Decode and validate opaque cursor token."""
    try:
        padding = "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise UsageValidationError(
            "Invalid cursor token.",
            details={"cursor": token},
            error_code="INVALID_CURSOR",
        ) from exc

    if not isinstance(payload, dict):
        raise UsageValidationError(
            "Invalid cursor token.",
            details={"cursor": token},
            error_code="INVALID_CURSOR",
        )
    if payload.get("v") != _CURSOR_VERSION:
        raise UsageValidationError(
            "Unsupported cursor version.",
            details={"cursor_version": payload.get("v")},
            error_code="INVALID_CURSOR",
        )

    command = payload.get("cmd")
    signature = payload.get("sig")
    offset = payload.get("offset")
    if (
        not isinstance(command, str)
        or not isinstance(signature, dict)
        or not isinstance(offset, int)
        or isinstance(offset, bool)
    ):
        raise UsageValidationError(
            "Invalid cursor token.",
            details={"cursor": token},
            error_code="INVALID_CURSOR",
        )
    if offset < 0:
        raise UsageValidationError(
            "Invalid cursor offset.",
            details={"offset": offset},
            error_code="INVALID_CURSOR",
        )

    return CursorState(command=command, signature=signature, offset=offset)
