"""Canonical query/filter model for discovery commands."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pcli.core.errors import UsageValidationError

type FilterValue = str | int | float

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 150
DEFAULT_MAX_DOCS = 200
DEFAULT_DISCOVERY_SORT = "-score,id"

_FILTER_ALIASES = {
    "doc_type": "document_type",
}


def _coerce_positive_int(name: str, value: Any, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise UsageValidationError(
            f"{name} must be a positive integer.",
            details={"field": name, "value": value},
            error_code="INVALID_INTEGER",
        )
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        raise UsageValidationError(
            f"{name} must be a positive integer.",
            details={"field": name, "value": value},
            error_code="INVALID_INTEGER",
        )
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized.isdigit():
            raise UsageValidationError(
                f"{name} must be a positive integer.",
                details={"field": name, "value": value},
                error_code="INVALID_INTEGER",
            )
        parsed = int(normalized)
    else:
        raise UsageValidationError(
            f"{name} must be a positive integer.",
            details={"field": name, "value": value},
            error_code="INVALID_INTEGER",
        )
    if parsed <= 0:
        raise UsageValidationError(
            f"{name} must be greater than zero.",
            details={"field": name, "value": value},
            error_code="INVALID_INTEGER",
        )
    return parsed


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_filter_value(value: Any) -> FilterValue | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    if isinstance(value, list):
        if any(isinstance(item, (dict, list)) for item in value):
            return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
        normalized_items: list[str] = []
        for item in value:
            normalized_item = _normalize_filter_value(item)
            if normalized_item is None:
                continue
            normalized_items.append(str(normalized_item))
        if not normalized_items:
            return None
        return ",".join(normalized_items)
    return str(value)


def normalize_search_filters(filters: dict[str, Any]) -> dict[str, FilterValue]:
    """Normalize passthrough filter keys and scalar/list values."""
    normalized: dict[str, FilterValue] = {}
    for raw_key, raw_value in filters.items():
        key = raw_key.strip()
        if not key:
            raise UsageValidationError(
                "Filter key must not be empty.",
                details={"key": raw_key},
                error_code="INVALID_FILTER_KEY",
            )
        canonical_key = _FILTER_ALIASES.get(key, key)
        normalized_value = _normalize_filter_value(raw_value)
        if normalized_value is None:
            continue
        normalized[canonical_key] = normalized_value
    return normalized


@dataclass(slots=True, frozen=True)
class CanonicalDocumentSearch:
    """Canonical discovery search model used by adapter commands."""

    query: str | None
    custom_field_query: str | None
    page: int
    page_size: int
    max_docs: int
    sort: str = DEFAULT_DISCOVERY_SORT
    filters: dict[str, FilterValue] = field(default_factory=dict)

    def to_reduce_params(self) -> dict[str, FilterValue]:
        """Convert model into keyword arguments accepted by pypaperless reduce()."""
        params: dict[str, FilterValue] = {
            "page": self.page,
            "page_size": self.page_size,
            "sort": self.sort,
        }
        if self.query is not None:
            params["query"] = self.query
        if self.custom_field_query is not None:
            params["custom_field_query"] = self.custom_field_query
        params.update(self.filters)
        return params

    def signature_payload(self) -> dict[str, Any]:
        """Stable payload for future cursor/signature logic."""
        return {
            "query": self.query,
            "custom_field_query": self.custom_field_query,
            "page": self.page,
            "page_size": self.page_size,
            "sort": self.sort,
            "max_docs": self.max_docs,
            "filters": {key: self.filters[key] for key in sorted(self.filters)},
        }


def canonicalize_document_search(
    *,
    query: str | None = None,
    custom_field_query: str | None = None,
    page: Any = None,
    page_size: Any = None,
    max_docs: Any = None,
    top: Any = None,
    sort: str | None = None,
    filters: dict[str, Any] | None = None,
) -> CanonicalDocumentSearch:
    """Normalize raw discovery values into canonical search model."""
    normalized_page = _coerce_positive_int("page", page, default=DEFAULT_PAGE)
    normalized_page_size = _coerce_positive_int("page_size", page_size, default=DEFAULT_PAGE_SIZE)

    max_docs_input = max_docs if max_docs is not None else top
    normalized_max_docs = _coerce_positive_int(
        "max_docs",
        max_docs_input,
        default=DEFAULT_MAX_DOCS,
    )
    normalized_sort = _normalize_text(sort) or DEFAULT_DISCOVERY_SORT

    return CanonicalDocumentSearch(
        query=_normalize_text(query),
        custom_field_query=_normalize_text(custom_field_query),
        page=normalized_page,
        page_size=normalized_page_size,
        max_docs=normalized_max_docs,
        sort=normalized_sort,
        filters=normalize_search_filters(filters or {}),
    )
