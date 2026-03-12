"""Tests for reusable resource handler helpers."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest

from pcli.adapters.resource_handler import (
    apply_mutation_fields,
    coerce_mutation_fields,
    create_resource_sync,
    delete_resource_sync,
    fetch_resource_sync,
    fetch_singleton_sync,
    list_resource_sync,
    mutation_error_details,
    require_confirmation,
    resolve_only_changed,
    serialize_resource,
    serialize_resource_list,
    update_resource_sync,
)
from pcli.core.errors import UsageValidationError


@dataclass(slots=True)
class _FakeField:
    name: str


class _FakeDraft:
    def __init__(self) -> None:
        self.name: str | None = None
        self._saved = False

    def _get_dataclass_fields(self) -> list[_FakeField]:
        return [_FakeField("name")]

    async def save(self) -> int:
        self._saved = True
        return 42


class _FakeItem:
    def __init__(self, item_id: int) -> None:
        self.id = item_id
        self.name: str = "old"
        self._updated_only_changed: bool | None = None
        self._data = {
            "id": item_id,
            "created": dt.date(2026, 1, 1),
            "updated": dt.datetime(2026, 1, 1, 2, 3, 4),
        }

    def _get_dataclass_fields(self) -> list[_FakeField]:
        return [_FakeField("id"), _FakeField("name")]

    async def update(self, *, only_changed: bool = True) -> bool:
        self._updated_only_changed = only_changed
        return True

    async def delete(self) -> bool:
        return True


class _ReduceCtx:
    def __init__(self, helper: _FakeHelper, kwargs: dict[str, Any]) -> None:
        self._helper = helper
        self._kwargs = kwargs

    async def __aenter__(self) -> _FakeHelper:
        self._helper._last_reduce_kwargs = self._kwargs
        return self._helper

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        _ = (exc_type, exc, tb)
        return False


class _FakePage:
    def __init__(self, item: _FakeItem, *, page: int, page_size: int) -> None:
        self.items = [item]
        self.count = 1
        self.current_page = page
        self.page_size = page_size
        self.next_page = None
        self.previous_page = page - 1 if page > 1 else None


class _FakeHelper:
    def __init__(self) -> None:
        self.request_permissions = False
        self._last_reduce_kwargs: dict[str, Any] | None = None
        self._last_requested_id: int | None = None
        self._item = _FakeItem(7)

    async def __call__(self, item_id: int) -> _FakeItem:
        self._last_requested_id = item_id
        return _FakeItem(item_id)

    def draft(self) -> _FakeDraft:
        return _FakeDraft()

    def reduce(self, **kwargs: Any) -> _ReduceCtx:
        return _ReduceCtx(self, kwargs)

    def pages(self, *, page: int = 1, page_size: int = 150) -> Any:
        async def _iterator() -> Any:
            yield _FakePage(self._item, page=page, page_size=page_size)

        return _iterator()


class _FakeWorkflows:
    def __init__(self) -> None:
        self.actions = _FakeHelper()
        self.triggers = _FakeHelper()


class _FakeClient:
    def __init__(self) -> None:
        self.is_initialized = False
        self.init_calls = 0
        self.tags = _FakeHelper()
        self.workflows = _FakeWorkflows()
        self.status: Any = None

    async def initialize(self) -> None:
        self.init_calls += 1
        self.is_initialized = True


class _FakeSingletonHelper:
    async def __call__(self) -> _FakeItem:
        return _FakeItem(99)


def test_mutation_field_helpers_and_confirmation() -> None:
    fields = coerce_mutation_fields({"name": "x", "count": "2", "enabled": "true", "tags": "1,2"})
    assert fields == {"name": "x", "count": 2, "enabled": True, "tags": [1, 2]}

    assert resolve_only_changed({}) is True
    assert resolve_only_changed({"only_changed": "false"}) is False

    require_confirmation({"yes": "true"}, command_path="docs delete")
    with pytest.raises(UsageValidationError) as exc:
        require_confirmation({}, command_path="docs delete")
    assert exc.value.payload.code == "CONFIRMATION_REQUIRED"


def test_apply_mutation_fields_rejects_unknown_fields() -> None:
    item = _FakeItem(1)
    apply_mutation_fields(item, {"name": "new-name"})
    assert item.name == "new-name"

    with pytest.raises(UsageValidationError) as exc:
        apply_mutation_fields(item, {"unknown_field": 1}, error_code="INVALID_UPDATE_FIELDS")
    assert exc.value.payload.code == "INVALID_UPDATE_FIELDS"


def test_resource_crud_sync_helpers() -> None:
    client = _FakeClient()

    page = list_resource_sync(
        client,
        helper_name="tags",
        page=2,
        page_size=25,
        filters={"name__icontains": "inv", "id__in": [1, 2, 3]},
        full_perms=True,
    )
    assert client.init_calls == 1
    assert len(page.items) == 1
    assert page.count == 1
    assert page.page == 2
    assert page.page_size == 25
    assert client.tags._last_reduce_kwargs == {"name__icontains": "inv", "id__in": "1,2,3"}
    assert client.tags.request_permissions is False

    item = fetch_resource_sync(client, helper_name="tags", item_id=11, full_perms=True)
    assert isinstance(item, _FakeItem)
    assert item.id == 11
    assert client.tags.request_permissions is False

    created = create_resource_sync(client, helper_name="tags", fields={"name": "created"})
    assert created == 42

    updated = update_resource_sync(item, fields={"name": "updated"}, only_changed=False)
    assert updated is True
    assert item.name == "updated"
    assert item._updated_only_changed is False

    deleted = delete_resource_sync(item)
    assert deleted is True


def test_resource_helpers_support_dotted_helper_paths() -> None:
    client = _FakeClient()

    action = fetch_resource_sync(client, helper_name="workflows.actions", item_id=5)
    assert isinstance(action, _FakeItem)
    assert action.id == 5

    page = list_resource_sync(
        client,
        helper_name="workflows.triggers",
        page=1,
        page_size=10,
        filters={"name__icontains": "auto"},
    )
    assert page.count == 1
    assert client.workflows.triggers._last_reduce_kwargs == {"name__icontains": "auto"}


def test_fetch_singleton_sync() -> None:
    client = _FakeClient()
    client.status = _FakeSingletonHelper()
    item = fetch_singleton_sync(client, helper_name="status")
    assert isinstance(item, _FakeItem)
    assert item.id == 99


def test_create_resource_rejects_unknown_fields() -> None:
    client = _FakeClient()
    with pytest.raises(UsageValidationError) as exc:
        create_resource_sync(client, helper_name="tags", fields={"invalid": "x"})
    assert exc.value.payload.code == "INVALID_CREATE_FIELDS"


def test_serialize_resource_helpers_and_error_detail_extraction() -> None:
    item = _FakeItem(3)
    serialized = serialize_resource(item)
    assert serialized["id"] == 3
    assert serialized["created"] == "2026-01-01"
    assert serialized["updated"] == "2026-01-01T02:03:04"
    assert serialize_resource_list([item])[0]["id"] == 3

    class _WithPayload(Exception):
        def __init__(self) -> None:
            super().__init__("boom")
            self.payload = {"detail": "server rejected"}

    assert mutation_error_details(_WithPayload())["server_payload"] == {"detail": "server rejected"}


def test_list_resource_rejects_non_positive_pagination_values() -> None:
    client = _FakeClient()
    with pytest.raises(UsageValidationError) as page_exc:
        list_resource_sync(client, helper_name="tags", page=0, page_size=10)
    assert page_exc.value.payload.code == "INVALID_PAGE"

    with pytest.raises(UsageValidationError) as size_exc:
        list_resource_sync(client, helper_name="tags", page=1, page_size=0)
    assert size_exc.value.payload.code == "INVALID_PAGE_SIZE"


def test_missing_helper_path_raises_unsupported_resource() -> None:
    client = _FakeClient()
    with pytest.raises(UsageValidationError) as exc:
        fetch_resource_sync(client, helper_name="workflows.missing", item_id=1)
    assert exc.value.payload.code == "UNSUPPORTED_RESOURCE"
