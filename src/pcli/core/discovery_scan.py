"""Bounded discovery batches with document/hit positions, not projected-row offsets."""

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass, replace
from typing import Any

from pcli.core.cursor import encode_cursor
from pcli.core.errors import UsageValidationError
from pcli.models.discovery import CanonicalDocumentSearch


@dataclass
class ScanResult:
    items: list[dict[str, Any]]
    meta: dict[str, Any]


async def _scan_entries(
    search: CanonicalDocumentSearch,
    fetch: Callable[[CanonicalDocumentSearch], AsyncGenerator[Any]],
    offset: int,
    selected_ids: list[int] | None,
    fetch_size: int,
) -> AsyncGenerator[Any]:
    if selected_ids is not None:
        ids = list(dict.fromkeys(selected_ids))
        end = min(len(ids), offset + search.max_docs + 1)
        for start in range(offset, end, fetch_size):
            window = ids[start : min(start + fetch_size, end)]
            batch = replace(
                search,
                page=1,
                page_size=len(window),
                max_docs=len(window),
                filters={**search.filters, "id__in": ",".join(map(str, window))},
            )
            async with aclosing(fetch(batch)) as documents:
                by_id = {getattr(doc, "id", None): doc async for doc in documents}
            for doc_id in window:
                yield by_id.pop(doc_id, None)
    else:
        skip = offset % fetch_size
        batch = replace(
            search,
            page=offset // fetch_size + 1,
            page_size=fetch_size,
            max_docs=search.max_docs + skip + 1,
        )
        async with aclosing(fetch(batch)) as documents:
            index = 0
            async for document in documents:
                if index >= skip:
                    yield document
                index += 1


async def scan_batch(
    *,
    search: CanonicalDocumentSearch,
    fetch: Callable[[CanonicalDocumentSearch], AsyncGenerator[Any]],
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
    emit: Callable[[dict[str, Any]], None] | None = None,
) -> ScanResult:
    """Consume lazily; retain rows only when no streaming sink is supplied.

    A single document lookahead distinguishes budget stops from exhaustion. Fetches
    remain page-granular; transport pages are independent of the output row limit.
    """
    fetch_size = min(search.page_size, search.max_docs + 1, 150)
    if max_matches is not None:
        fetch_size = min(fetch_size, max_matches + 1)
    if max_pages is not None:
        fetch_size = min(fetch_size, max_pages + 1)
    items: list[dict[str, Any]] = []
    count = pages_used = chars_used = docs_scanned = docs_with_hits = 0

    def finish(position: int, hit: int, reason: str) -> ScanResult:
        complete = reason == "exhausted"
        return ScanResult(
            items,
            {
                "count": count,
                "matches": count,
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

    position = offset
    async with aclosing(_scan_entries(search, fetch, offset, selected_ids, fetch_size)) as entries:
        async for document in entries:
            first_hit = hit_offset if position == offset else 0
            if position - offset >= search.max_docs:
                return finish(position, first_hit, "max_docs")
            if count >= search.page_size:
                return finish(position, first_hit, "page_size")
            if max_matches is not None and count >= max_matches:
                return finish(position, first_hit, "stop_after_matches")
            if document is None:
                position += 1  # Missing selected IDs still advance the selector position.
                continue
            cost = page_cost(document)
            if max_pages is not None and pages_used + cost > max_pages:
                return budget_stop(position, first_hit, "max_pages_total")
            pages_used += cost
            docs_scanned += 1
            hits = project(document)
            emitted = False
            for hit_index in range(first_hit, len(hits)):
                if count >= search.page_size:
                    return finish(position, hit_index, "page_size")
                if max_matches is not None and count >= max_matches:
                    return finish(position, hit_index, "stop_after_matches")
                row = hits[hit_index]
                chars = character_cost(row)
                if max_chars is not None and chars_used + chars > max_chars:
                    return budget_stop(position, hit_index, "max_chars_total")
                if emit is None:
                    items.append(row)
                else:
                    emit(row)
                count += 1
                chars_used += chars
                if not emitted:
                    docs_with_hits += 1
                    emitted = True
            position += 1
    return finish(position, 0, "exhausted")
