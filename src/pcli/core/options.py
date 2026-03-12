"""Global options and value parsing helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pcli.core.errors import UsageValidationError


class FormatMode(StrEnum):
    """Supported output formats."""

    JSON = "json"
    TEXT = "text"
    NDJSON = "ndjson"


def parse_bool(value: str) -> bool:
    """Parse a boolean string."""
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    lowered = value.strip().lower()
    if lowered in truthy:
        return True
    if lowered in falsy:
        return False
    raise UsageValidationError(
        f"Invalid boolean value: {value!r}.",
        details={"value": value},
        error_code="INVALID_BOOLEAN",
    )


def parse_scalar(value: str) -> Any:
    """Coerce string into scalar JSON-like value."""
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered == "null":
        return None
    if lowered in {"true", "false"}:
        return lowered == "true"

    # JSON list/object payload support.
    if normalized.startswith("[") or normalized.startswith("{"):
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            pass

    # CSV list support for simple payloads.
    if "," in normalized and not normalized.startswith("["):
        return [parse_scalar(part.strip()) for part in normalized.split(",")]

    try:
        return int(normalized)
    except ValueError:
        pass

    try:
        return float(normalized)
    except ValueError:
        pass

    return value


@dataclass(slots=True)
class GlobalOptions:
    """Global option set for command execution."""

    url: str | None = None
    token: str | None = None
    profile: str | None = None
    format_mode: FormatMode = FormatMode.JSON
    raw: bool = False
    verbose: bool = False
    timeout: int | None = None

    @classmethod
    def from_updates(cls, updates: dict[str, str]) -> GlobalOptions:
        """Build global options from normalized key/value updates."""
        options = cls()
        if "url" in updates:
            options.url = updates["url"]
        if "token" in updates:
            options.token = updates["token"]
        if "profile" in updates:
            options.profile = updates["profile"]
        if "format" in updates:
            try:
                options.format_mode = FormatMode(updates["format"])
            except ValueError as exc:
                raise UsageValidationError(
                    f"Invalid format: {updates['format']!r}.",
                    details={"allowed": [mode.value for mode in FormatMode]},
                    error_code="INVALID_FORMAT",
                ) from exc
        if "raw" in updates:
            options.raw = parse_bool(updates["raw"])
        if "verbose" in updates:
            options.verbose = parse_bool(updates["verbose"])
        if "timeout" in updates:
            try:
                options.timeout = int(updates["timeout"])
            except ValueError as exc:
                raise UsageValidationError(
                    f"Invalid timeout: {updates['timeout']!r}.",
                    details={"value": updates["timeout"]},
                    error_code="INVALID_TIMEOUT",
                ) from exc

        return options
