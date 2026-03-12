"""Validation helpers for command constraints."""

from __future__ import annotations

from pcli.core.errors import UsageValidationError


def require(
    condition: bool, *, message: str, code: str, details: dict[str, object] | None = None
) -> None:
    """Raise structured validation error when condition is false."""
    if not condition:
        raise UsageValidationError(message, details=details or {}, error_code=code)


def validate_raw_allowed(*, raw: bool, command_path: str) -> None:
    """Validate command support for raw output mode."""
    raw_allowed_commands = {
        "docs download",
        "docs preview",
        "docs thumbnail",
    }
    if raw and command_path not in raw_allowed_commands:
        raise UsageValidationError(
            "raw=true is only allowed for docs download/preview/thumbnail.",
            details={"command": command_path},
            error_code="RAW_NOT_ALLOWED",
        )
