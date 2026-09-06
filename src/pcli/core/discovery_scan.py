"""Bounded discovery batches with document/hit positions, not projected-row offsets."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from pcli.core.cursor import encode_cursor
from pcli.core.errors import UsageValidationError
from pcli.models.discovery import CanonicalDocumentSearch


@dataclass
class ScanResult:
    items: list[dict[str, Any]]
    meta: dict[str, Any]


def scan_batch(
    *,
    search: CanonicalDocumentSearch,
    fetch: Callable[[CanonicalDocumentSearch], list[Any]],
    project: Callable[[Any], list[dict[str, Any]]],
    character_cost: Callable[[dict[str, Any]], int],
    page_cost: Callable[[Any], int],
    command: str,
    signature: dict[str, Any],
    offset: int,
    hit_offset: int = 0,
    selected_ids: list[int] | None = None,
    max_pages: int | None = None,
    max_chars: int | None = None,
    max_matches: int | None = None,
) -> ScanResult:
    # Fetch one lookahead document to distinguish a hard cap from actual exhaustion.
    if selected_ids is not None:
        ids = list(dict.fromkeys(selected_ids))
        window = ids[offset : offset + search.max_docs + 1]
        documents = (
            fetch(
                replace(
                    search,
                    page=1,
                    max_docs=len(window),
                    filters={**search.filters, "id__in": ",".join(map(str, window))},
                )
            )
            if window
            else []
        )
        by_id = {getattr(doc, "id", None): doc for doc in documents}
        entries = [by_id.get(doc_id) for doc_id in window]
    else:
        skip = offset % search.page_size
        documents = fetch(
            replace(
                search,
                page=offset // search.page_size + 1,
                max_docs=search.max_docs + skip + 1,
            )
        )
        entries = documents[skip:]

    items: list[dict[str, Any]] = []
    pages_used = chars_used = docs_scanned = docs_with_hits = 0

    def finish(position: int, hit: int, reason: str) -> ScanResult:
        complete = reason == "exhausted"
        return ScanResult(
            items,
            {
                "count": len(items),
                "matches": len(items),
                "docs_scanned": docs_scanned,
                "docs_with_hits": docs_with_hits,
                "pages_used": pages_used,
                "chars_used": chars_used,
                "complete": complete,
                "stop_reason": reason,
                "next_cursor": None
                if complete
                else encode_cursor(
                    command=command,
                    signature=signature,
                    offset=position,
                    hit_offset=hit,
                ),
            },
        )

    def budget_stop(position: int, hit: int, reason: str) -> ScanResult:
        if position == offset and hit == hit_offset:
            raise UsageValidationError(
                "The next document or hit cannot fit the budget; increase the indicated limit.",
                details={"limit": reason},
                error_code="BUDGET_TOO_SMALL",
            )
        return finish(position, hit, reason)

    for index, document in enumerate(entries):
        position = offset + index
        first_hit = hit_offset if index == 0 else 0
        if index >= search.max_docs:
            return finish(position, first_hit, "max_docs")
        if len(items) >= search.page_size:
            return finish(position, first_hit, "page_size")
        if max_matches is not None and len(items) >= max_matches:
            return finish(position, first_hit, "stop_after_matches")
        if document is None:
            continue  # Missing/inaccessible selected IDs still advance the selector position.
        cost = page_cost(document)
        if max_pages is not None and pages_used + cost > max_pages:
            return budget_stop(position, first_hit, "max_pages_total")
        pages_used += cost
        docs_scanned += 1
        hits = project(document)
        emitted = False
        for hit_index in range(first_hit, len(hits)):
            if len(items) >= search.page_size:
                return finish(position, hit_index, "page_size")
            if max_matches is not None and len(items) >= max_matches:
                return finish(position, hit_index, "stop_after_matches")
            row = hits[hit_index]
            chars = character_cost(row)
            if max_chars is not None and chars_used + chars > max_chars:
                return budget_stop(position, hit_index, "max_chars_total")
            items.append(row)
            chars_used += chars
            if not emitted:
                docs_with_hits += 1
                emitted = True
    return finish(offset + len(entries), 0, "exhausted")
