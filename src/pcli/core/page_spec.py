"""Page specification parsing helpers for document retrieval commands."""

from __future__ import annotations

from pcli.core.errors import UsageValidationError
from pcli.core.options import parse_scalar


def parse_max_pages(value: str | None) -> int | None:
    """Parse optional `max_pages` argument as positive integer."""
    if value is None:
        return None
    parsed = parse_scalar(value)
    if not isinstance(parsed, int) or isinstance(parsed, bool) or parsed <= 0:
        raise UsageValidationError(
            "max_pages must be a positive integer.",
            details={"value": value},
            error_code="INVALID_MAX_PAGES",
        )
    return parsed


def parse_pages_spec(value: str, *, max_pages: int | None = None) -> list[int]:
    """Parse pages spec (`1`, `1-3`, `1,3,5-7`) into normalized page numbers."""
    raw = value.strip()
    if not raw:
        raise UsageValidationError(
            "pages must be a non-empty page specification.",
            details={"value": value},
            error_code="INVALID_PAGES",
        )

    intervals: list[tuple[int, int]] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            raise UsageValidationError(
                "pages contains an empty segment.",
                details={"value": value},
                error_code="INVALID_PAGES",
            )
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2:
                raise UsageValidationError(
                    "pages range is invalid.",
                    details={"token": token},
                    error_code="INVALID_PAGES",
                )
            start_text, end_text = parts[0].strip(), parts[1].strip()
            if not start_text.isdigit() or not end_text.isdigit():
                raise UsageValidationError(
                    "pages range endpoints must be positive integers.",
                    details={"token": token},
                    error_code="INVALID_PAGES",
                )
            start = int(start_text)
            end = int(end_text)
            if start <= 0 or end <= 0 or start > end:
                raise UsageValidationError(
                    "pages range must be ascending and 1-based.",
                    details={"token": token},
                    error_code="INVALID_PAGES",
                )
            intervals.append((start, end))
            continue

        if not token.isdigit():
            raise UsageValidationError(
                "pages values must be positive integers.",
                details={"token": token},
                error_code="INVALID_PAGES",
            )
        page = int(token)
        if page <= 0:
            raise UsageValidationError(
                "pages values must be 1-based.",
                details={"token": token},
                error_code="INVALID_PAGES",
            )
        intervals.append((page, page))

    # Validate all segments before applying the cap; do not expand huge ranges first.
    pages: list[int] = []
    for start, end in sorted(intervals):
        if pages:
            start = max(start, pages[-1] + 1)
        if max_pages is not None:
            end = min(end, start + max_pages - len(pages) - 1)
        if len(pages) + max(0, end - start + 1) > 100_000:
            raise UsageValidationError(
                "Page selection is too large; narrow pages or set max_pages.",
                error_code="PAGE_SELECTION_TOO_LARGE",
            )
        pages.extend(range(start, end + 1))
        if max_pages is not None and len(pages) >= max_pages:
            break
    return pages


def normalize_page_selection(
    *,
    pages: str | None,
    max_pages: str | None,
) -> list[int] | None:
    """Parse and normalize page selection with optional max-pages cap."""
    parsed_max_pages = parse_max_pages(max_pages)
    if pages is None:
        return None
    return parse_pages_spec(pages, max_pages=parsed_max_pages)
