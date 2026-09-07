"""Resume real document positions across API pages and per-call budget boundaries."""

import asyncio
import io
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import pytest

from pcli.cli.docs import _read_stdin_ids, _run_discovery_scan
from pcli.core.cursor import decode_cursor
from pcli.core.discovery_scan import ScanResult, scan_batch
from pcli.core.errors import PcliError, UsageValidationError
from pcli.core.options import FormatMode
from pcli.models.discovery import CanonicalDocumentSearch, canonicalize_document_search


@dataclass
class Document:
    id: int
    hits: int = 3


def run_batch(
    documents: list[Document],
    *,
    cursor: str | None = None,
    max_docs: int = 2,
    page_size: int = 2,
    selected_ids: list[int] | None = None,
    **budgets: Any,
) -> ScanResult:
    search = canonicalize_document_search(max_docs=max_docs, page_size=page_size)

    async def fetch(batch: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        matches = documents
        if "id__in" in batch.filters:
            ids = str(batch.filters["id__in"]).split(",")
            matches = [doc for doc in documents if str(doc.id) in ids]
        start = (batch.page - 1) * batch.page_size
        for document in matches[start : start + batch.max_docs]:
            yield document

    state = decode_cursor(cursor) if cursor else None
    return asyncio.run(
        scan_batch(
            search=search,
            fetch=fetch,
            project=lambda doc: [
                {"doc_id": doc.id, "hit": hit, "text": "12345"} for hit in range(doc.hits)
            ],
            character_cost=lambda row: len(row["text"]),
            page_cost=lambda doc: 1,
            command="docs.skim",
            signature={},
            offset=state.offset if state else 0,
            hit_offset=state.hit_offset if state else 0,
            selected_ids=selected_ids,
            **budgets,
        )
    )


@pytest.mark.parametrize("max_docs", [1, 2, 5])
@pytest.mark.parametrize("page_size", [1, 2, 4])
@pytest.mark.parametrize("budget", [{}, {"max_matches": 1}, {"max_chars": 7}, {"max_pages": 1}])
@pytest.mark.parametrize("selected", [False, True])
def test_resumption_never_drops_or_repeats_hits(
    max_docs: int,
    page_size: int,
    budget: dict[str, Any],
    selected: bool,
) -> None:
    documents = [Document(i) for i in range(1, 8)]
    cursor = None
    found: list[tuple[int, int]] = []
    for _ in range(30):
        result = run_batch(
            documents,
            cursor=cursor,
            max_docs=max_docs,
            page_size=page_size,
            selected_ids=[7, 2, 999, 3, 4, 5, 6, 1] if selected else None,
            **budget,
        )
        found.extend((row["doc_id"], row["hit"]) for row in result.items)
        next_cursor = result.meta["next_cursor"]
        if result.meta["complete"]:
            assert next_cursor is None
            break
        assert next_cursor and next_cursor != cursor
        cursor = next_cursor
    else:
        pytest.fail("Scan failed to make progress")
    order = [7, 2, 3, 4, 5, 6, 1] if selected else list(range(1, 8))
    assert found == [(i, hit) for i in order for hit in range(3)]


@pytest.mark.parametrize("hits, consumed", [(1, 2), (3, 1)])
def test_stream_emits_before_reading_more_and_closes_on_budget(hits: int, consumed: int) -> None:
    events: list[str] = []

    async def fetch(search: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        assert search.page_size == 2
        try:
            for i in range(2000):
                events.append(f"fetch:{i}")
                yield Document(i, hits=hits)
        finally:
            events.append("closed")

    result = asyncio.run(
        scan_batch(
            search=canonicalize_document_search(max_docs=2000),
            fetch=fetch,
            project=lambda doc: [{"id": doc.id}] * doc.hits,
            character_cost=lambda row: 0,
            page_cost=lambda doc: 1,
            command="docs.skim",
            signature={},
            offset=0,
            max_matches=1,
            emit=lambda row: events.append(f"emit:{row['id']}"),
        )
    )
    assert events[:2] == ["fetch:0", "emit:0"]
    assert events[-1] == "closed"
    assert sum(event.startswith("fetch:") for event in events) == consumed
    assert result.items == []
    assert result.meta["count"] == 1
    assert result.meta["complete"] is False


def test_selected_ids_use_bounded_reorder_windows() -> None:
    windows: list[list[int]] = []

    async def fetch(search: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        ids = list(map(int, str(search.filters["id__in"]).split(",")))
        windows.append(ids)
        for i in sorted(ids):
            yield Document(i)

    result = asyncio.run(
        scan_batch(
            search=canonicalize_document_search(max_docs=2000),
            fetch=fetch,
            project=lambda doc: [{"id": doc.id}],
            character_cost=lambda row: 0,
            page_cost=lambda doc: 1,
            command="docs.peek",
            signature={},
            offset=0,
            selected_ids=list(range(2000, 0, -1)),
            max_matches=1,
        )
    )
    assert result.items == [{"id": 2000}]
    assert windows == [[2000, 1999]]


def test_sparse_selected_scan_expands_without_changing_input_rank() -> None:
    windows: list[int] = []

    async def fetch(search: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        ids = list(map(int, str(search.filters["id__in"]).split(",")))
        windows.append(len(ids))
        for i in sorted(ids):
            yield Document(i, hits=int(i == 700))

    result = asyncio.run(
        scan_batch(
            search=canonicalize_document_search(max_docs=500, page_size=500),
            fetch=fetch,
            project=lambda doc: [{"id": doc.id}] * doc.hits,
            character_cost=lambda row: 0,
            page_cost=lambda doc: 1,
            command="docs.skim",
            signature={},
            offset=0,
            selected_ids=list(range(1000, 0, -1)),
            max_matches=1,
        )
    )
    assert result.items == [{"id": 700}]
    assert result.meta["docs_scanned"] == 301
    assert windows == [2, 150, 150]


def test_sink_failure_stops_fetching_and_closes_source() -> None:
    events: list[str] = []

    async def fetch(search: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        try:
            yield Document(1)
            pytest.fail("Should not fetch after a sink failure")
        finally:
            events.append("closed")

    def emit(row: dict[str, Any]) -> None:
        raise BrokenPipeError()

    with pytest.raises(BrokenPipeError):
        asyncio.run(
            scan_batch(
                search=canonicalize_document_search(),
                fetch=fetch,
                project=lambda doc: [{"id": doc.id}],
                character_cost=lambda row: 0,
                page_cost=lambda doc: 1,
                command="docs.find",
                signature={},
                offset=0,
                emit=emit,
            )
        )
    assert events == ["closed"]


@pytest.mark.parametrize("failure", [None, TimeoutError, BrokenPipeError])
def test_cli_scan_closes_client_on_own_loop(failure: type[Exception] | None) -> None:
    loops: list[asyncio.AbstractEventLoop] = []

    class Client:
        async def close(self) -> None:
            loops.append(asyncio.get_running_loop())

    async def fetch(search: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        loops.append(asyncio.get_running_loop())
        yield Document(1)
        if failure:
            raise failure()

    def run() -> ScanResult:
        return _run_discovery_scan(
            client=Client(),
            mode=FormatMode.JSON,
            search=canonicalize_document_search(),
            fetch=fetch,
            project=lambda doc: [{"id": doc.id}],
            character_cost=lambda row: 0,
            page_cost=lambda doc: 1,
            command="docs.find",
            signature={},
            offset=0,
        )

    if failure:
        with pytest.raises(failure):
            run()
    else:
        assert run().meta["complete"] is True
    assert len(loops) == 2 and loops[0] is loops[1]
    assert loops[0].is_closed()


def test_stdin_does_not_buffer_raw_input(monkeypatch: pytest.MonkeyPatch) -> None:
    class LinesOnly(io.StringIO):
        def read(self, size: int | None = -1) -> str:
            pytest.fail("Read IDs line-by-line instead of buffering raw stdin")

    monkeypatch.setattr("sys.stdin", LinesOnly("1\n2\n"))
    assert _read_stdin_ids() == ([1, 2], True)


def test_empty_hit_batch_is_not_exhaustion() -> None:
    documents = [Document(i, hits=0 if i < 5 else 1) for i in range(1, 6)]
    first = run_batch(documents)
    assert first.items == []
    assert first.meta["complete"] is False
    second = run_batch(documents, cursor=first.meta["next_cursor"])
    third = run_batch(documents, cursor=second.meta["next_cursor"])
    assert third.items[0]["doc_id"] == 5
    assert third.meta["complete"] is True


def test_resumption_allows_changing_budgets_and_transport_page_sizes() -> None:
    documents = [Document(i) for i in range(1, 8)]
    cursor = None
    found: list[tuple[int, int]] = []
    for batch in range(30):
        result = run_batch(
            documents,
            cursor=cursor,
            page_size=4,
            max_docs=1 if batch % 2 else 7,
            max_matches=1 if batch % 2 else 3,
        )
        found.extend((row["doc_id"], row["hit"]) for row in result.items)
        if result.meta["complete"]:
            break
        cursor = result.meta["next_cursor"]
    assert found == [(i, hit) for i in range(1, 8) for hit in range(3)]


def test_selected_order_precedes_limit_and_missing_ids_advance() -> None:
    documents = [Document(i, hits=1) for i in [2, 7, 9]]
    first = run_batch(documents, selected_ids=[9, 2, 999, 7])
    assert [row["doc_id"] for row in first.items] == [9, 2]
    second = run_batch(documents, selected_ids=[9, 2, 999, 7], cursor=first.meta["next_cursor"])
    assert [row["doc_id"] for row in second.items] == [7]
    assert second.meta["complete"] is True


def test_impossible_budget_is_an_actionable_error() -> None:
    with pytest.raises(UsageValidationError, match="cannot fit"):
        run_batch([Document(1)], max_chars=1)


@pytest.mark.parametrize(
    "payload",
    [
        '{"ok":false,"error":{"code":"NETWORK_ERROR"}}\n',
        '{"type":"error","error":{}}\n',
        '{"type":"item","id":1}\n',
    ],
)
def test_failed_or_unterminated_input_cannot_become_success(
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    with pytest.raises(PcliError):
        _read_stdin_ids(allow_partial=True)


def test_partial_input_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"type":"item","id":1}\n'
        '{"type":"summary","meta":{"complete":false,"next_cursor":"token"}}\n'
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    with pytest.raises(UsageValidationError):
        _read_stdin_ids()
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert _read_stdin_ids(allow_partial=True) == ([1], False)


def test_sort_mapping_and_unsupported_composite_search_sort() -> None:
    params = canonicalize_document_search(query="invoice", sort="-created").to_reduce_params()
    assert params["ordering"] == "-created"
    assert "sort" not in params
    for sort in ["-created,id", "--created", "custom_field_1,title", "custom_field_bad"]:
        with pytest.raises(UsageValidationError):
            canonicalize_document_search(query="invoice", sort=sort)
