"""Tests for document search adapter behavior."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from pcli.adapters.document_search import DocumentSearchAdapter
from pcli.models.discovery import FilterValue, canonicalize_document_search


@dataclass(slots=True)
class FakeDocument:
    id: int


class FakeDocumentsHelper:
    def __init__(self, items: list[FakeDocument]) -> None:
        self._items = items
        self.reduce_calls: list[dict[str, Any]] = []

    def reduce(self, **kwargs: FilterValue) -> AbstractAsyncContextManager[FakeDocumentsHelper]:
        self.reduce_calls.append(kwargs)

        @asynccontextmanager
        async def _context() -> AsyncIterator[FakeDocumentsHelper]:
            yield self

        return _context()

    def __aiter__(self) -> AsyncIterator[FakeDocument]:
        async def _iter() -> AsyncIterator[FakeDocument]:
            for item in self._items:
                yield item

        return _iter()


class FakePaperlessClient:
    def __init__(self, items: list[FakeDocument], *, initialized: bool = False) -> None:
        self.is_initialized = initialized
        self.initialize_calls = 0
        self.documents = FakeDocumentsHelper(items)

    async def initialize(self) -> None:
        self.initialize_calls += 1
        self.is_initialized = True


def test_iter_documents_initializes_client_and_applies_reduce_params() -> None:
    adapter = DocumentSearchAdapter()
    client = FakePaperlessClient([FakeDocument(1), FakeDocument(2), FakeDocument(3)])
    search = canonicalize_document_search(
        query="invoices",
        max_docs=2,
        filters={"doc_type": [7, 8], "tag__id": 4},
    )

    async def run() -> list[FakeDocument]:
        return [item async for item in adapter.iter_documents(cast(Any, client), search)]

    results = asyncio.run(run())
    assert [item.id for item in results] == [1, 2]
    assert client.initialize_calls == 1
    assert client.documents.reduce_calls == [
        {
            "page": 1,
            "page_size": 150,
            "sort": "-score,id",
            "query": "invoices",
            "document_type": "7,8",
            "tag__id": 4,
        }
    ]


def test_iter_documents_skips_initialize_when_client_is_ready() -> None:
    adapter = DocumentSearchAdapter()
    client = FakePaperlessClient([FakeDocument(1)], initialized=True)
    search = canonicalize_document_search(max_docs=1)

    async def run() -> list[FakeDocument]:
        return [item async for item in adapter.iter_documents(cast(Any, client), search)]

    results = asyncio.run(run())
    assert [item.id for item in results] == [1]
    assert client.initialize_calls == 0


def test_collect_documents_sync_wraps_async_execution() -> None:
    adapter = DocumentSearchAdapter()
    client = FakePaperlessClient([FakeDocument(11), FakeDocument(12)])
    search = canonicalize_document_search(max_docs=1)
    results = adapter.collect_documents_sync(cast(Any, client), search)
    assert [item.id for item in results] == [11]
