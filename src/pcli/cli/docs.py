"""Document command group."""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import replace
from typing import Annotated, Any

import typer

from pcli.adapters.client import create_client
from pcli.adapters.document_search import DocumentSearchAdapter
from pcli.cli.io import emit_success
from pcli.core.errors import UsageValidationError
from pcli.core.options import GlobalOptions, parse_scalar
from pcli.core.parsing import parse_tokens
from pcli.core.validation import validate_raw_allowed
from pcli.models.discovery import DEFAULT_DISCOVERY_SORT, canonicalize_document_search

app = typer.Typer(help="Document discovery and management.", add_completion=False)

_FIND_KNOWN_OPTION_KEYS = {
    "query",
    "custom_field_query",
    "page",
    "page_size",
    "max_docs",
    "top",
    "fields",
    "sort",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_DEFAULT_FIND_FIELDS = ["id", "title", "created", "score", "snippet"]
_SNIPPET_MAX_CHARS = 240
_FACETS_KNOWN_OPTION_KEYS = _FIND_KNOWN_OPTION_KEYS | {"by", "facet_scope", "top_values"}
_DEFAULT_FACET_SCOPE = "page"
_DEFAULT_TOP_VALUES = 20
_FACETS_ALL_MAX_DOCS = 2_147_483_647
_SUPPORTED_FACET_FIELDS = {"tags", "doc_type", "document_type", "correspondent", "year"}
_FACET_FIELD_MAP = {
    "tags": "tags",
    "doc_type": "document_type",
    "document_type": "document_type",
    "correspondent": "correspondent",
    "year": "year",
}


def _parse_fields(value: str | None) -> list[str]:
    if value is None:
        return list(_DEFAULT_FIND_FIELDS)
    parsed = parse_scalar(value)
    raw_items: list[Any]
    if isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = [part for part in value.split(",")]

    fields: list[str] = []
    for raw_item in raw_items:
        field_name = str(raw_item).strip()
        if field_name:
            fields.append(field_name)
    if not fields:
        raise UsageValidationError(
            "fields must contain at least one field name.",
            details={"value": value},
            error_code="INVALID_FIELDS",
        )
    return fields


def _normalize_scalar_output(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _document_score(document: Any) -> float | None:
    search_hit = getattr(document, "search_hit", None)
    if search_hit is None:
        return None
    score = getattr(search_hit, "score", None)
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _synthesize_snippet(document: Any) -> str | None:
    search_hit = getattr(document, "search_hit", None)
    highlights = []
    if search_hit is not None:
        highlights = [
            getattr(search_hit, "highlights", None),
            getattr(search_hit, "note_highlights", None),
        ]
    for highlight in highlights:
        if isinstance(highlight, str) and highlight.strip():
            normalized = re.sub(r"\s+", " ", highlight).strip()
            if len(normalized) <= _SNIPPET_MAX_CHARS:
                return normalized
            return normalized[: _SNIPPET_MAX_CHARS - 3].rstrip() + "..."

    content = getattr(document, "content", None)
    if not isinstance(content, str):
        return None
    normalized_content = re.sub(r"\s+", " ", content).strip()
    if not normalized_content:
        return None
    if len(normalized_content) <= _SNIPPET_MAX_CHARS:
        return normalized_content
    return normalized_content[: _SNIPPET_MAX_CHARS - 3].rstrip() + "..."


def _sorted_find_documents(documents: list[Any]) -> list[Any]:
    def _sort_key(document: Any) -> tuple[int, float, int]:
        score = _document_score(document)
        doc_id = getattr(document, "id", None)
        normalized_id = int(doc_id) if isinstance(doc_id, int) else 0
        if score is None:
            return (1, 0.0, normalized_id)
        return (0, -score, normalized_id)

    return sorted(documents, key=_sort_key)


def _project_find_document(document: Any, fields: list[str]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field_name in fields:
        if field_name == "score":
            projected[field_name] = _document_score(document)
            continue
        if field_name == "snippet":
            projected[field_name] = _synthesize_snippet(document)
            continue
        projected[field_name] = _normalize_scalar_output(getattr(document, field_name, None))
    return projected


def _parse_by_fields(value: str | None) -> list[str]:
    if value is None:
        raise UsageValidationError(
            "docs facets requires by=<facet-list>.",
            error_code="MISSING_FACETS_BY",
        )
    parsed = parse_scalar(value)
    raw_items: list[Any]
    if isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = [part for part in value.split(",")]

    by_fields: list[str] = []
    for raw_item in raw_items:
        name = str(raw_item).strip().lower()
        if not name:
            continue
        if name not in _SUPPORTED_FACET_FIELDS:
            raise UsageValidationError(
                "Unsupported facet field.",
                details={"field": name, "allowed": sorted(_SUPPORTED_FACET_FIELDS)},
                error_code="INVALID_FACET_FIELD",
            )
        by_fields.append(name)
    if not by_fields:
        raise UsageValidationError(
            "docs facets requires by=<facet-list>.",
            error_code="MISSING_FACETS_BY",
        )
    return by_fields


def _parse_facet_scope(value: str | None) -> str:
    if value is None:
        return _DEFAULT_FACET_SCOPE
    normalized = value.strip().lower()
    if normalized not in {"page", "all"}:
        raise UsageValidationError(
            "facet_scope must be one of: page, all.",
            details={"value": value},
            error_code="INVALID_FACET_SCOPE",
        )
    return normalized


def _parse_top_values(value: str | None) -> int:
    if value is None:
        return _DEFAULT_TOP_VALUES
    parsed = parse_scalar(value)
    if not isinstance(parsed, int) or isinstance(parsed, bool) or parsed <= 0:
        raise UsageValidationError(
            "top_values must be a positive integer.",
            details={"value": value},
            error_code="INVALID_TOP_VALUES",
        )
    return parsed


def _extract_facet_values(document: Any, internal_field: str) -> list[Any]:
    if internal_field == "tags":
        tags = getattr(document, "tags", None)
        if not isinstance(tags, list):
            return []
        return [tag for tag in tags if tag is not None]
    if internal_field == "year":
        created = getattr(document, "created", None)
        if isinstance(created, dt.datetime):
            return [created.year]
        if isinstance(created, dt.date):
            return [created.year]
        if isinstance(created, str):
            try:
                return [dt.datetime.fromisoformat(created).year]
            except ValueError:
                return []
        return []

    value = getattr(document, internal_field, None)
    if value is None:
        return []
    return [value]


def _build_facets(
    documents: list[Any],
    by_fields: list[str],
    *,
    top_values: int,
) -> dict[str, list[dict[str, Any]]]:
    facets: dict[str, list[dict[str, Any]]] = {}
    for output_field in by_fields:
        internal_field = _FACET_FIELD_MAP[output_field]
        counter: Counter[Any] = Counter()
        for document in documents:
            for value in _extract_facet_values(document, internal_field):
                counter[value] += 1
        ranked = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
        facets[output_field] = [
            {"value": _normalize_scalar_output(value), "count": count}
            for value, count in ranked[:top_values]
        ]
    return facets


@app.command(
    "find",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_find(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Query/filter options."),
    ] = None,
) -> None:
    """Find candidate documents for LLM shortlist workflows."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_FIND_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs find accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    query = parsed.updates.get("query")
    if query is None or not str(query).strip():
        raise UsageValidationError(
            "docs find requires query=<search terms>.",
            error_code="MISSING_QUERY",
        )

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("max_docs"),
        top=parsed.updates.get("top"),
        sort=parsed.updates.get("sort"),
        filters=parsed.passthrough_filters,
    )
    fields = _parse_fields(parsed.updates.get("fields"))

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs find")

    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    sorted_documents = (
        _sorted_find_documents(documents)
        if search.sort == DEFAULT_DISCOVERY_SORT
        else documents
    )
    rows = [_project_find_document(doc, fields) for doc in sorted_documents]

    emit_success(
        resource="docs",
        action="find",
        data={"items": rows},
        meta={
            "count": len(rows),
            "page": search.page,
            "page_size": search.page_size,
            "max_docs": search.max_docs,
            "query": search.query,
            "sort": search.sort,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "facets",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_facets(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Query/facet/filter options."),
    ] = None,
) -> None:
    """Aggregate facet counts over matching documents."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_FACETS_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs facets accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    query = parsed.updates.get("query")
    if query is None or not str(query).strip():
        raise UsageValidationError(
            "docs facets requires query=<search terms>.",
            error_code="MISSING_QUERY",
        )
    by_fields = _parse_by_fields(parsed.updates.get("by"))
    facet_scope = _parse_facet_scope(parsed.updates.get("facet_scope"))
    top_values = _parse_top_values(parsed.updates.get("top_values"))

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("max_docs"),
        top=parsed.updates.get("top"),
        sort=parsed.updates.get("sort"),
        filters=parsed.passthrough_filters,
    )
    has_explicit_doc_limit = "max_docs" in parsed.updates or "top" in parsed.updates
    if facet_scope == "page":
        search = replace(search, max_docs=min(search.max_docs, search.page_size))
    else:
        search = replace(search, page=1)
        if not has_explicit_doc_limit:
            search = replace(search, max_docs=_FACETS_ALL_MAX_DOCS)

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs facets")
    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    facets = _build_facets(documents, by_fields, top_values=top_values)

    emit_success(
        resource="docs",
        action="facets",
        data={"facets": facets},
        meta={
            "query": search.query,
            "facet_scope": facet_scope,
            "top_values": top_values,
            "scanned_docs": len(documents),
            "profile": runtime_context.profile,
            "max_docs": (
                None
                if facet_scope == "all" and not has_explicit_doc_limit
                else search.max_docs
            ),
        },
    )
