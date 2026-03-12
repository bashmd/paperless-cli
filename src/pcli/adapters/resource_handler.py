"""Reusable helpers for Paperless resource CRUD operations."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pcli.core.errors import UsageValidationError
from pcli.core.options import parse_bool, parse_scalar


@dataclass(slots=True, frozen=True)
class ListPage:
    """Normalized page data for list-style resource operations."""

    items: list[Any]
    count: int
    page: int
    page_size: int
    next_page: int | None
    previous_page: int | None


def mutation_error_details(exc: Exception) -> dict[str, Any]:
    """Extract server payload details from an exception where possible."""
    payload = getattr(exc, "payload", None)
    if payload is not None:
        return {"server_payload": payload, "error": str(exc)}
    if len(exc.args) > 0:
        return {"server_payload": exc.args[0], "error": str(exc)}
    return {"error": str(exc)}


def coerce_mutation_fields(raw_fields: Mapping[str, str]) -> dict[str, Any]:
    """Parse mutation fields from CLI strings into typed values."""
    return {key: parse_scalar(value) for key, value in raw_fields.items()}


def resolve_only_changed(updates: Mapping[str, str], *, key: str = "only_changed") -> bool:
    """Resolve `only_changed` style switches with default=True semantics."""
    if key not in updates:
        return True
    return parse_bool(updates[key])


def require_confirmation(
    updates: Mapping[str, str],
    *,
    command_path: str,
    key: str = "yes",
) -> None:
    """Enforce explicit confirmation (`yes=true`) for destructive actions."""
    if parse_bool(updates.get(key, "false")):
        return
    raise UsageValidationError(
        f"{command_path} requires yes=true.",
        details={key: updates.get(key)},
        error_code="CONFIRMATION_REQUIRED",
    )


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    return value


def serialize_resource(item: Any) -> dict[str, Any]:
    """Serialize a pypaperless model-like object into JSON-safe dictionary."""
    if isinstance(item, dict):
        return {str(key): _normalize_json_value(value) for key, value in item.items()}
    raw_data = getattr(item, "_data", None)
    if isinstance(raw_data, dict):
        return {str(key): _normalize_json_value(value) for key, value in raw_data.items()}
    raise UsageValidationError(
        "Resource payload cannot be serialized.",
        details={"type": type(item).__name__},
        error_code="INVALID_RESOURCE_PAYLOAD",
    )


def serialize_resource_item(item: Any) -> dict[str, Any]:
    """Backward-compatible alias used by command modules."""
    return serialize_resource(item)


def serialize_resource_list(items: list[Any]) -> list[dict[str, Any]]:
    """Serialize a list of pypaperless model-like objects."""
    return [serialize_resource(item) for item in items]


def _model_field_names(model: Any) -> set[str]:
    getter = getattr(model, "_get_dataclass_fields", None)
    if not callable(getter):
        return set()
    return {str(field.name) for field in getter()}


def apply_mutation_fields(
    model: Any,
    fields: Mapping[str, Any],
    *,
    error_code: str = "INVALID_MUTATION_FIELDS",
) -> None:
    """Apply mutation fields while validating field names against dataclass fields."""
    known_fields = _model_field_names(model)
    unknown_fields = sorted(field for field in fields if field not in known_fields)
    if known_fields and unknown_fields:
        raise UsageValidationError(
            "Unknown mutation field(s).",
            details={
                "unknown_fields": unknown_fields,
                "allowed_fields": sorted(known_fields),
            },
            error_code=error_code,
        )
    for key, value in fields.items():
        setattr(model, key, value)


def _normalize_filter_value(value: Any) -> str | int:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    return str(value)


async def _ensure_initialized(client: Any) -> None:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()


def _resolve_helper(client: Any, helper_name: str) -> Any:
    current = client
    for attr in helper_name.split("."):
        current = getattr(current, attr, None)
        if current is None:
            raise UsageValidationError(
                "Resource helper is not available.",
                details={"resource": helper_name, "segment": attr},
                error_code="UNSUPPORTED_RESOURCE",
            )
    return current


async def list_resource(
    client: Any,
    *,
    helper_name: str,
    page: int = 1,
    page_size: int = 150,
    filters: Mapping[str, Any] | None = None,
    full_perms: bool = False,
) -> ListPage:
    """List one page of resources for a helper."""
    if page <= 0:
        raise UsageValidationError(
            "page must be a positive integer.",
            details={"page": page},
            error_code="INVALID_PAGE",
        )
    if page_size <= 0:
        raise UsageValidationError(
            "page_size must be a positive integer.",
            details={"page_size": page_size},
            error_code="INVALID_PAGE_SIZE",
        )

    await _ensure_initialized(client)
    helper = _resolve_helper(client, helper_name)
    previous_perms = getattr(helper, "request_permissions", False)
    if full_perms and hasattr(helper, "request_permissions"):
        helper.request_permissions = True

    normalized_filters = {
        key: _normalize_filter_value(value) for key, value in (filters or {}).items()
    }

    try:
        if normalized_filters and hasattr(helper, "reduce"):
            async with helper.reduce(**normalized_filters):
                page_data = await anext(helper.pages(page=page, page_size=page_size))
        else:
            page_data = await anext(helper.pages(page=page, page_size=page_size))
    except StopAsyncIteration:
        return ListPage(
            items=[],
            count=0,
            page=page,
            page_size=page_size,
            next_page=None,
            previous_page=None,
        )
    finally:
        if full_perms and hasattr(helper, "request_permissions"):
            helper.request_permissions = previous_perms

    return ListPage(
        items=list(getattr(page_data, "items", [])),
        count=int(getattr(page_data, "count", 0)),
        page=page,
        page_size=page_size,
        next_page=getattr(page_data, "next_page", None),
        previous_page=getattr(page_data, "previous_page", None),
    )


def list_resource_sync(
    client: Any,
    *,
    helper_name: str,
    page: int = 1,
    page_size: int = 150,
    filters: Mapping[str, Any] | None = None,
    full_perms: bool = False,
) -> ListPage:
    """Synchronous wrapper for list_resource."""
    return asyncio.run(
        list_resource(
            client,
            helper_name=helper_name,
            page=page,
            page_size=page_size,
            filters=filters,
            full_perms=full_perms,
        )
    )


async def fetch_resource(
    client: Any,
    *,
    helper_name: str,
    item_id: int,
    full_perms: bool = False,
) -> Any:
    """Fetch one resource by ID from a helper."""
    await _ensure_initialized(client)
    helper = _resolve_helper(client, helper_name)
    previous_perms = getattr(helper, "request_permissions", False)
    if full_perms and hasattr(helper, "request_permissions"):
        helper.request_permissions = True
    try:
        return await helper(item_id)
    finally:
        if full_perms and hasattr(helper, "request_permissions"):
            helper.request_permissions = previous_perms


def fetch_resource_sync(
    client: Any,
    *,
    helper_name: str,
    item_id: int,
    full_perms: bool = False,
) -> Any:
    """Synchronous wrapper for fetch_resource."""
    return asyncio.run(
        fetch_resource(
            client,
            helper_name=helper_name,
            item_id=item_id,
            full_perms=full_perms,
        )
    )


async def create_resource(
    client: Any,
    *,
    helper_name: str,
    fields: Mapping[str, Any],
) -> Any:
    """Create a resource via helper draft/save contract."""
    await _ensure_initialized(client)
    helper = _resolve_helper(client, helper_name)
    if not hasattr(helper, "draft"):
        raise UsageValidationError(
            "Resource does not support create.",
            details={"resource": helper_name},
            error_code="UNSUPPORTED_OPERATION",
        )
    draft = helper.draft()
    apply_mutation_fields(draft, fields, error_code="INVALID_CREATE_FIELDS")
    return await draft.save()


def create_resource_sync(
    client: Any,
    *,
    helper_name: str,
    fields: Mapping[str, Any],
) -> Any:
    """Synchronous wrapper for create_resource."""
    return asyncio.run(create_resource(client, helper_name=helper_name, fields=fields))


async def update_resource(
    resource_item: Any,
    *,
    fields: Mapping[str, Any],
    only_changed: bool = True,
) -> bool:
    """Update a fetched resource instance via model update contract."""
    apply_mutation_fields(resource_item, fields, error_code="INVALID_UPDATE_FIELDS")
    return bool(await resource_item.update(only_changed=only_changed))


def update_resource_sync(
    resource_item: Any,
    *,
    fields: Mapping[str, Any],
    only_changed: bool = True,
) -> bool:
    """Synchronous wrapper for update_resource."""
    return asyncio.run(update_resource(resource_item, fields=fields, only_changed=only_changed))


async def delete_resource(resource_item: Any) -> bool:
    """Delete a fetched resource instance."""
    return bool(await resource_item.delete())


def delete_resource_sync(resource_item: Any) -> bool:
    """Synchronous wrapper for delete_resource."""
    return asyncio.run(delete_resource(resource_item))
