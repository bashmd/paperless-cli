"""Resume real document positions across API pages and per-call budget boundaries."""

import io
from dataclasses import dataclass
from typing import Any

import pytest

from pcli.cli.docs import _read_stdin_ids
from pcli.core.cursor import decode_cursor
from pcli.core.discovery_scan import ScanResult, scan_batch
from pcli.core.errors import PcliError, UsageValidationError
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

    def fetch(batch: CanonicalDocumentSearch) -> list[Document]:
        matches = documents
        if "id__in" in batch.filters:
            ids = str(batch.filters["id__in"]).split(",")
            matches = [doc for doc in documents if str(doc.id) in ids]
        start = (batch.page - 1) * batch.page_size
        return matches[start : start + batch.max_docs]

    state = decode_cursor(cursor) if cursor else None
    return scan_batch(
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


@pytest.mark.parametrize("max_docs", [1, 2, 5])
@pytest.mark.parametrize("page_size", [1, 2, 4])
@pytest.mark.parametrize("budget", [{}, {"max_matches": 1}, {"max_chars": 7}, {"max_pages": 1}])
def test_resumption_never_drops_or_repeats_hits(
    max_docs: int,
    page_size: int,
    budget: dict[str, Any],
) -> None:
    documents = [Document(i) for i in range(1, 8)]
    cursor = None
    found: list[tuple[int, int]] = []
    for _ in range(30):
        result = run_batch(
            documents, cursor=cursor, max_docs=max_docs, page_size=page_size, **budget
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
    assert found == [(i, hit) for i in range(1, 8) for hit in range(3)]


def test_empty_hit_batch_is_not_exhaustion() -> None:
    documents = [Document(i, hits=0 if i < 5 else 1) for i in range(1, 6)]
    first = run_batch(documents)
    assert first.items == []
    assert first.meta["complete"] is False
    second = run_batch(documents, cursor=first.meta["next_cursor"])
    third = run_batch(documents, cursor=second.meta["next_cursor"])
    assert third.items[0]["doc_id"] == 5
    assert third.meta["complete"] is True


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
