"""Retrieval source parsing and fallback resolution."""

from __future__ import annotations

from pcli.core.errors import UsageValidationError

SUPPORTED_RETRIEVAL_SOURCES = {"auto", "ocr", "archive", "original"}


def parse_retrieval_source(value: str | None) -> str:
    """Parse and validate retrieval source option."""
    if value is None:
        return "auto"
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_RETRIEVAL_SOURCES:
        raise UsageValidationError(
            "source must be one of: auto, ocr, archive, original.",
            details={"value": value},
            error_code="INVALID_SOURCE",
        )
    return normalized


def resolve_source_candidates(*, source: str, has_page_filter: bool) -> list[str]:
    """Resolve ordered candidate sources based on source mode and page usage."""
    if has_page_filter:
        if source == "auto":
            return ["archive", "original"]
        return [source]
    if source == "auto":
        return ["ocr"]
    return [source]
