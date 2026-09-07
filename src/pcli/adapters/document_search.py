"""Document discovery adapter built on top of pypaperless helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, aclosing
from typing import Any, Protocol, cast

from pcli.models.discovery import CanonicalDocumentSearch, FilterValue


class _DocumentsHelperProtocol(Protocol):
    def reduce(self, **kwargs: FilterValue) -> AbstractAsyncContextManager[object]: ...
    def __aiter__(self) -> AsyncIterator[Any]: ...


class _PaperlessDiscoveryClientProtocol(Protocol):
    @property
    def is_initialized(self) -> bool: ...

    documents: _DocumentsHelperProtocol

    async def initialize(self) -> None: ...


class DocumentSearchAdapter:
    """Adapter used by discovery commands (`find`, `facets`, `peek`, `skim`)."""

    async def iter_documents(
        self,
        client: _PaperlessDiscoveryClientProtocol,
        search: CanonicalDocumentSearch,
    ) -> AsyncGenerator[Any]:
        """Iterate matching documents using canonical query/filter params."""
        if not client.is_initialized:
            await client.initialize()

        params = search.to_reduce_params()
        yielded = 0
        async with client.documents.reduce(**params):
            # pypaperless implements __aiter__ as an async generator. Close it before
            # the owning loop exits, including on early budgets and broken pipes.
            async with aclosing(cast(AsyncGenerator[Any], aiter(client.documents))) as documents:
                async for item in documents:
                    yield item
                    yielded += 1
                    if yielded >= search.max_docs:
                        break

    async def collect_documents(
        self,
        client: _PaperlessDiscoveryClientProtocol,
        search: CanonicalDocumentSearch,
    ) -> list[Any]:
        """Collect matching documents into a list."""
        return [item async for item in self.iter_documents(client, search)]

    def collect_documents_sync(
        self,
        client: _PaperlessDiscoveryClientProtocol,
        search: CanonicalDocumentSearch,
    ) -> list[Any]:
        """Synchronous wrapper for CLI command handlers."""
        return asyncio.run(self.collect_documents(client, search))
