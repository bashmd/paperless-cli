"""Tests for generic resource handler abstraction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from pcli.adapters.resource_handler import (
    ResourceHandler,
    coerce_resource_fields,
    serialize_resource_item,
)
from pcli.core.errors import UsageValidationError


@dataclass
class FakeItem:
    id: int
    title: str = "old"
    _data: dict[str, Any] | None = None
    _updated_only_changed: bool | None = None

    def __post_init__(self) -> None:
        if self._data is None:
            self._data = {"id": self.id, "title": self.title}

    async def update(self, *, only_changed: bool = True) -> bool:
        self._updated_only_changed = only_changed
        return True

    async def delete(self) -> bool:
        return True


@dataclass
class FakeDraft:
    payload: dict[str, Any]

    async def save(self) -> int:
        return 99


class FakeHelper:
    def __init__(self) -> None:
        self.items = [FakeItem(1), FakeItem(2)]
        self.reduce_calls: list[dict[str, Any]] = []
        self.draft_payloads: list[dict[str, Any]] = []
        self.request_permissions_called = False

    @asynccontextmanager
    async def reduce(self, **kwargs: Any) -> AsyncIterator[object]:
        self.reduce_calls.append(kwargs)
        yield object()

    def __aiter__(self) -> AsyncIterator[FakeItem]:
        async def _iterator() -> AsyncIterator[FakeItem]:
            for item in self.items:
                yield item

        return _iterator()

    async def __call__(self, resource_id: int | str) -> FakeItem:
        for item in self.items:
            if item.id == int(resource_id):
                return item
        raise LookupError(resource_id)

    def draft(self, **kwargs: Any) -> FakeDraft:
        self.draft_payloads.append(kwargs)
        return FakeDraft(payload=kwargs)

    def request_permissions(self) -> None:
        self.request_permissions_called = True


class FakeClient:
    def __init__(self) -> None:
        self.is_initialized = False
        self.initialize_calls = 0
        self.tags = FakeHelper()

    async def initialize(self) -> None:
        self.is_initialized = True
        self.initialize_calls += 1


def test_coerce_fields_and_serialize_item() -> None:
    assert coerce_resource_fields({"count": "3", "flag": "true", "ids": "1,2"}) == {
        "count": 3,
        "flag": True,
        "ids": [1, 2],
    }
    assert serialize_resource_item(FakeItem(7, title="x")) == {"id": 7, "title": "x"}


def test_list_sync_initializes_and_passes_filters() -> None:
    client = FakeClient()
    handler = ResourceHandler(client=client, helper_attr="tags")
    items = handler.list_items_sync(page=2, page_size=5, filters={"name__icontains": "x"})

    assert client.initialize_calls == 1
    assert len(items) == 2
    assert client.tags.reduce_calls == [{"page": 2, "page_size": 5, "name__icontains": "x"}]


def test_get_create_update_delete_sync_flows() -> None:
    client = FakeClient()
    handler = ResourceHandler(client=client, helper_attr="tags")

    item = handler.get_sync(1, full_perms=True)
    assert item.id == 1
    assert client.tags.request_permissions_called is True

    created = handler.create_sync({"name": "urgent"})
    assert created == 99
    assert client.tags.draft_payloads == [{"name": "urgent"}]

    updated = handler.update_sync(1, fields={"title": "new"}, only_changed=False)
    assert updated is True
    assert item.title == "new"
    assert item._updated_only_changed is False

    deleted = handler.delete_sync(1)
    assert deleted is True


def test_missing_helper_raises_unsupported_resource() -> None:
    client = FakeClient()
    handler = ResourceHandler(client=client, helper_attr="missing")
    with pytest.raises(UsageValidationError):
        handler.list_items_sync(page=1, page_size=1)
