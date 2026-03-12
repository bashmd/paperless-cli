"""Reusable resource command abstraction for CRUD/read-only endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pcli.core.errors import UsageValidationError
from pcli.core.options import parse_scalar


class _ResourceItemProtocol(Protocol):
    _data: dict[str, Any]

    async def update(self, *, only_changed: bool = True) -> bool: ...
    async def delete(self) -> bool: ...


class _ResourceDraftProtocol(Protocol):
    async def save(self) -> int | str | tuple[int, int]: ...


class _ResourceHelperProtocol(Protocol):
    def reduce(self, **kwargs: Any) -> AbstractAsyncContextManager[object]: ...
    def __aiter__(self) -> AsyncIterator[Any]: ...
    async def __call__(self, resource_id: int | str) -> _ResourceItemProtocol: ...
    def draft(self, **kwargs: Any) -> _ResourceDraftProtocol: ...

    # optional capabilities on securable helpers
    def request_permissions(self) -> Any: ...


class _PaperlessLikeClientProtocol(Protocol):
    is_initialized: bool

    async def initialize(self) -> None: ...


def coerce_resource_fields(raw_fields: dict[str, str]) -> dict[str, Any]:
    """Coerce raw field token values into typed Python values."""
    coerced: dict[str, Any] = {}
    for key, value in raw_fields.items():
        coerced[key] = parse_scalar(value)
    return coerced


def serialize_resource_item(item: Any) -> dict[str, Any]:
    """Serialize helper resource item/model to JSON-friendly dictionary."""
    raw_data = getattr(item, "_data", None)
    if isinstance(raw_data, dict):
        return {str(key): value for key, value in raw_data.items()}
    return {}


@dataclass(slots=True)
class ResourceHandler:
    """Generic async/sync operations for resource helpers."""

    client: _PaperlessLikeClientProtocol
    helper_attr: str

    def _helper(self) -> _ResourceHelperProtocol:
        helper = getattr(self.client, self.helper_attr, None)
        if helper is None:
            raise UsageValidationError(
                "Requested resource helper is not available.",
                details={"resource": self.helper_attr},
                error_code="UNSUPPORTED_RESOURCE",
            )
        return cast(_ResourceHelperProtocol, helper)

    async def _ensure_initialized(self) -> None:
        if not self.client.is_initialized:
            await self.client.initialize()

    async def list_items(
        self,
        *,
        page: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        await self._ensure_initialized()
        helper = self._helper()
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        params.update(filters or {})
        async with helper.reduce(**params):
            items: list[Any] = []
            async for item in helper:
                items.append(item)
            return items

    async def get(
        self,
        resource_id: int | str,
        *,
        full_perms: bool = False,
    ) -> Any:
        await self._ensure_initialized()
        helper = self._helper()
        if full_perms and hasattr(helper, "request_permissions"):
            helper.request_permissions()
        return await helper(resource_id)

    async def create(self, fields: dict[str, Any]) -> int | str | tuple[int, int]:
        await self._ensure_initialized()
        helper = self._helper()
        if not hasattr(helper, "draft"):
            raise UsageValidationError(
                "Create is not supported for this resource.",
                details={"resource": self.helper_attr},
                error_code="UNSUPPORTED_OPERATION",
            )
        draft = helper.draft(**fields)
        return await draft.save()

    async def update(
        self,
        resource_id: int | str,
        *,
        fields: dict[str, Any],
        only_changed: bool = True,
        full_perms: bool = False,
    ) -> bool:
        item = await self.get(resource_id, full_perms=full_perms)
        for key, value in fields.items():
            setattr(item, key, value)
        return bool(await item.update(only_changed=only_changed))

    async def delete(self, resource_id: int | str, *, full_perms: bool = False) -> bool:
        item = await self.get(resource_id, full_perms=full_perms)
        return bool(await item.delete())

    def list_items_sync(
        self,
        *,
        page: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        return asyncio.run(self.list_items(page=page, page_size=page_size, filters=filters))

    def get_sync(
        self,
        resource_id: int | str,
        *,
        full_perms: bool = False,
    ) -> Any:
        return asyncio.run(self.get(resource_id, full_perms=full_perms))

    def create_sync(self, fields: dict[str, Any]) -> int | str | tuple[int, int]:
        return asyncio.run(self.create(fields))

    def update_sync(
        self,
        resource_id: int | str,
        *,
        fields: dict[str, Any],
        only_changed: bool = True,
        full_perms: bool = False,
    ) -> bool:
        return asyncio.run(
            self.update(
                resource_id,
                fields=fields,
                only_changed=only_changed,
                full_perms=full_perms,
            )
        )

    def delete_sync(self, resource_id: int | str, *, full_perms: bool = False) -> bool:
        return asyncio.run(self.delete(resource_id, full_perms=full_perms))
